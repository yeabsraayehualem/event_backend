"""What happens when a lead is won: its event, a deposit invoice, and a planning project.

Every step is idempotent, so winning a lead twice (or converting an old won lead
by hand) never duplicates records — it only fills in whatever is still missing.
"""

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from chatter.tracking import post_message
from event.models import Event, Project
from finance.models import CustomerInvoice, InvoiceLines

CENT = Decimal("0.01")


def deposit_percent():
    return Decimal(str(settings.LEAD_WON_DEPOSIT_PERCENT))


def split_amount(total, parts):
    """Split `total` into `parts` cent-exact amounts; any leftover cents go on the last one."""
    share = (total / parts).quantize(CENT, rounding=ROUND_DOWN)
    return [share] * (parts - 1) + [total - share * (parts - 1)]


def _ensure_event(lead):
    return Event.objects.get_or_create(
        lead=lead,
        defaults={
            "customer": lead.customer,
            "plan": lead.plan,
            "package": lead.package,
            "name": f"{lead.customer.name} — {lead.event_type.name if lead.event_type else lead.plan.name}",
            "event_type": lead.event_type.name if lead.event_type else "",
            "event_date": lead.plan_date,
            "guest_count": lead.guest_count,
            "location": lead.location,
        },
    )


def _deposit_invoice(lead, event):
    """Create the deposit invoice, or explain in the chatter why it could not be made."""
    if event.invoices.exists():
        return None, None
    package = lead.package
    contents = list(package.contents.order_by("id")) if package else []
    if package is None:
        return None, "No package was chosen, so no deposit invoice was created."
    if package.price <= 0:
        return None, f"The “{package.name}” package has no price, so no deposit invoice was created."
    if not contents:
        return None, f"The “{package.name}” package lists no services, so no deposit invoice was created."

    percent = deposit_percent()
    deposit = (package.price * percent / 100).quantize(CENT)
    invoice = CustomerInvoice.objects.create(
        event=event,
        customer=event.customer,
        plan=event.plan,
        package=package,
        milestone_name="Deposit",
        due_date=timezone.localdate() + timedelta(days=settings.LEAD_WON_INVOICE_DUE_DAYS),
    )
    for content, amount in zip(contents, split_amount(deposit, len(contents))):
        InvoiceLines.objects.create(invoice=invoice, content=content, inclusive_price=amount)
    invoice.refresh_from_db()
    return invoice, None


def _project_lead(lead, user):
    if lead.assigned_sales_person_id:
        return lead.assigned_sales_person
    if user is not None and user.is_authenticated:
        return user
    return User.objects.filter(role=User.Role.SUPER, is_active=True).order_by("id").first()


def _planning_project(lead, event, user):
    if Project.objects.filter(event=event).exists():
        return None, None
    project_lead = _project_lead(lead, user)
    if project_lead is None:
        return None, "Nobody could be made project lead, so no project was created."
    today = timezone.localdate()
    return Project.objects.create(
        name=f"{event.name} preparation",
        event=event,
        lead=project_lead,
        start_date=min(today, event.event_date),
        end_date=event.event_date,
    ), None


@transaction.atomic
def handle_won_lead(lead, user=None):
    """Create whatever is still missing for a won lead and log it on each record's chatter."""
    author = user if getattr(user, "is_authenticated", False) else None
    event, event_created = _ensure_event(lead)
    invoice, invoice_note = _deposit_invoice(lead, event)
    project, project_note = _planning_project(lead, event, user)

    origin = f"Created automatically when lead #{lead.id} was won."
    created = []
    if event_created:
        post_message(event, body=origin, author=author)
        created.append(f"event #{event.id} “{event.name}”")
    if invoice:
        post_message(invoice, body=f"{origin} Deposit of {format(deposit_percent().normalize(), 'f')}% of the package price.", author=author)
        created.append(f"deposit invoice {invoice.reference} (ETB {invoice.total:,.2f})")
    if project:
        post_message(project, body=origin, author=author)
        created.append(f"project “{project.name}” led by {project.lead.get_full_name() or project.lead}")

    lines = []
    if created:
        lines.append("Lead won — created " + ", ".join(created) + ".")
    lines += [note for note in (invoice_note, project_note) if note]
    if lines:
        post_message(lead, body="\n".join(lines), author=author)

    return {"event": event, "event_created": event_created, "invoice": invoice, "project": project}
