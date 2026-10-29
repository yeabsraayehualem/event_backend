"""Helpers that turn model changes into chatter messages, Odoo style.

Typical use in a DRF update view::

    before = snapshot(instance, TRACKED_FIELDS)
    serializer.save()
    log_changes(instance, before, TRACKED_FIELDS, request.user)
"""

from django.contrib.contenttypes.models import ContentType
from django.db import models

from chatter.models import Message, TrackingValue

EMPTY = ""


def _field_label(instance, name):
    try:
        return str(instance._meta.get_field(name).verbose_name).capitalize()
    except Exception:
        return name.replace("_", " ").capitalize()


def _display(instance, name):
    """Human readable value of a field, as shown in the change log."""
    field = instance._meta.get_field(name)
    if field.many_to_many:
        if not instance.pk:
            return EMPTY
        return ", ".join(sorted(_person_or_str(item) for item in getattr(instance, name).all()))
    value = getattr(instance, name)
    if value is None or value == "":
        return EMPTY
    if field.choices:
        return str(getattr(instance, f"get_{name}_display")())
    if isinstance(field, models.ForeignKey):
        return _person_or_str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _person_or_str(value):
    get_full_name = getattr(value, "get_full_name", None)
    if callable(get_full_name):
        return get_full_name() or str(value)
    return str(value)


def snapshot(instance, fields):
    return {name: _display(instance, name) for name in fields}


def post_message(record, body="", author=None, kind=Message.Kind.SYSTEM, changes=None):
    message = Message.objects.create(
        content_type=ContentType.objects.get_for_model(record, for_concrete_model=True),
        object_id=record.pk,
        author=author if getattr(author, "is_authenticated", False) else None,
        kind=kind,
        body=body,
    )
    if changes:
        TrackingValue.objects.bulk_create([
            TrackingValue(message=message, field=name, field_label=label, old_value=old, new_value=new)
            for name, label, old, new in changes
        ])
    return message


def log_changes(instance, before, fields, author=None, body="", record=None, labels=None):
    """Compare `before` with the instance's current values and log any differences.

    `record` lets a child object (e.g. a task) log onto its parent's chatter.
    """
    labels = labels or {}
    instance.refresh_from_db()
    after = snapshot(instance, fields)
    changes = [
        (name, labels.get(name) or _field_label(instance, name), before.get(name, EMPTY), after[name])
        for name in fields
        if before.get(name, EMPTY) != after[name]
    ]
    if not changes:
        return None
    return post_message(record or instance, body=body, author=author, kind=Message.Kind.TRACKING, changes=changes)
