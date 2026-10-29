from django.db import migrations, models
import django.db.models.deletion


def link_event_types(apps, schema_editor):
    """Turn each lead's free-text event type into an EventType under the lead's plan."""
    Lead = apps.get_model("crm", "Lead")
    EventType = apps.get_model("event", "EventType")
    for lead in Lead.objects.exclude(event_type="").iterator():
        name = lead.event_type.strip()
        if not name:
            continue
        event_type, _ = EventType.objects.get_or_create(plan_id=lead.plan_id, name=name)
        lead.event_type_link_id = event_type.id
        lead.save(update_fields=["event_type_link"])


def unlink_event_types(apps, schema_editor):
    Lead = apps.get_model("crm", "Lead")
    for lead in Lead.objects.exclude(event_type_link=None).select_related("event_type_link").iterator():
        lead.event_type = lead.event_type_link.name
        lead.save(update_fields=["event_type"])


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0006_lead_budget_tier_lead_event_type_lead_guest_count_and_more"),
        ("event", "0008_plan_event_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="event_type_link",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="leads", to="event.eventtype",
            ),
        ),
        migrations.RunPython(link_event_types, unlink_event_types),
        migrations.RemoveField(model_name="lead", name="event_type"),
        migrations.RenameField(model_name="lead", old_name="event_type_link", new_name="event_type"),
    ]
