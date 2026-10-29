from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404

from crm.models import Customers, Lead
from crm.serializers import CRMLeadCreateSerializer, LeadDetailSerializer, LeadsSerializer
from utils.formatter import Formatter
from utils.permissions import IsLeadAssigneeOrSuper, IsSalesOrSuper
from utils.views import SalesView
from utils.views import SuperView
from finance.models import CustomerInvoice
from event.models import Event, Plan
from chatter.tracking import log_changes, post_message, snapshot


User = get_user_model()
LEAD_TRACKED_FIELDS = ["status", "plan_date", "location", "package", "assigned_sales_person", "notes"]
LEAD_FIELD_LABELS = {
    "plan_date": "Event date",
    "package": "Package",
    "assigned_sales_person": "Sales person",
    "location": "Venue or location",
}
ACTIVE_STATUSES = [
    Lead.Status.LEAD,
    Lead.Status.CONTACTED,
    Lead.Status.CONSULTATION_SCHEDULED,
    Lead.Status.QUOTATION_SENT,
    Lead.Status.NEGOTIATION,
]


class SalesDashboard(SalesView):
    """CRM summary scoped to all leads for super users and owned leads for sales."""

    def get(self, request, *args, **kwargs):
        is_super = request.user.role == User.Role.SUPER
        leads = Lead.objects.all() if is_super else Lead.objects.filter(assigned_sales_person=request.user)
        start_raw = request.query_params.get("start_date")
        end_raw = request.query_params.get("end_date")
        start_date = parse_date(start_raw) if start_raw else None
        end_date = parse_date(end_raw) if end_raw else None
        if (start_raw and not start_date) or (end_raw and not end_date):
            raise ValidationError({"date": "Use YYYY-MM-DD for start_date and end_date."})
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"date": "start_date must be on or before end_date."})
        if start_date:
            leads = leads.filter(date__gte=start_date)
        if end_date:
            leads = leads.filter(date__lte=end_date)
        leads = leads.select_related("customer", "plan", "package", "assigned_sales_person")

        total = leads.count()
        won = leads.filter(status=Lead.Status.WON).count()
        lost = leads.filter(status=Lead.Status.LOST).count()
        closed = won + lost

        summary = {
            "total_leads": total,
            "active_leads": leads.filter(status__in=ACTIVE_STATUSES).count(),
            "assigned_leads": leads.filter(assigned_sales_person__isnull=False).count(),
            "won_leads": won,
            "lost_leads": lost,
            "conversion_rate": round((won / closed) * 100, 1) if closed else 0,
            "active_events": self._active_event_count(
                start_date, end_date, None if is_super else request.user
            ),
        }

        status_breakdown = [
            {
                "status": status_value,
                "label": label,
                "count": leads.filter(status=status_value).count(),
            }
            for status_value, label in Lead.Status.choices
        ]

        recent_leads = [
            {
                "id": lead.id,
                "customer_name": lead.customer.name,
                "phone": lead.customer.phone,
                "plan_name": lead.plan.name,
                "package_name": lead.package.name if lead.package else None,
                "plan_date": lead.plan_date.isoformat(),
                "created_date": lead.date.isoformat(),
                "status": lead.status,
                "status_label": lead.get_status_display(),
                "sales_person": (
                    lead.assigned_sales_person.get_full_name()
                    or lead.assigned_sales_person.phone
                    if lead.assigned_sales_person
                    else None
                ),
            }
            for lead in leads.order_by("-date", "-id")[:8]
        ]

        sales_people = User.objects.filter(role=User.Role.SALES)
        if not is_super:
            sales_people = sales_people.filter(pk=request.user.pk)
        sales_performance = []
        for person in sales_people.order_by("first_name", "last_name", "phone"):
            person_leads = Lead.objects.filter(assigned_sales_person=person)
            if start_date:
                person_leads = person_leads.filter(date__gte=start_date)
            if end_date:
                person_leads = person_leads.filter(date__lte=end_date)
            counts = person_leads.aggregate(
                active=Count("id", filter=Q(status__in=ACTIVE_STATUSES)),
                wins=Count("id", filter=Q(status=Lead.Status.WON)),
                losses=Count("id", filter=Q(status=Lead.Status.LOST)),
            )
            resolved = counts["wins"] + counts["losses"]
            sales_performance.append({
                "sales_person_id": person.id,
                "name": person.get_full_name() or person.phone,
                "active_leads": counts["active"],
                "won_leads": counts["wins"],
                "lost_leads": counts["losses"],
                "conversion_rate": round((counts["wins"] / resolved) * 100, 1) if resolved else 0,
            })

        return Response(Formatter.success(data={
            "scope": "all" if is_super else "assigned_to_me",
            "summary": summary,
            "status_breakdown": status_breakdown,
            "recent_leads": recent_leads,
            "sales_performance": sales_performance,
        }))

    @staticmethod
    def _active_event_count(start_date, end_date, sales_user=None):
        events = Event.objects.filter(status__in=[Event.Status.PLANNING, Event.Status.ACTIVE])
        if sales_user:
            events = events.filter(lead__assigned_sales_person=sales_user)
        if start_date:
            events = events.filter(event_date__gte=start_date)
        if end_date:
            events = events.filter(event_date__lte=end_date)
        return events.count()






class LeadFormOptions(APIView):
    """Choices needed to create a lead by hand: plans with their packages, and sales people."""

    permission_classes = [IsSalesOrSuper]

    def get(self, request):
        is_super = request.user.role == User.Role.SUPER
        plans = [
            {
                "id": plan.id,
                "name": plan.name,
                "packages": [{"id": package.id, "name": package.name} for package in plan.packages.all()],
            }
            for plan in Plan.objects.prefetch_related("packages").order_by("name")
        ]
        sales_people = [
            {"id": person.id, "name": person.get_full_name() or person.phone}
            for person in User.objects.filter(role=User.Role.SALES).order_by("first_name", "last_name", "phone")
        ] if is_super else []
        return Response({"plans": plans, "sales_people": sales_people, "can_assign_sales": is_super})


class CRMLeads(ListAPIView):
    """List leads for a status, scoped to the current sales user."""

    serializer_class = LeadsSerializer
    permission_classes = [IsSalesOrSuper]

    def get_queryset(self):
        status_value = self.request.query_params.get("status", Lead.Status.LEAD)
        valid_statuses = {value for value, _label in Lead.Status.choices}
        if status_value != "all" and status_value not in valid_statuses:
            raise ValidationError({
                "status": f"Choose one of: {', '.join(sorted(valid_statuses))}."
            })

        # Plan has a reverse one-to-many `packages` relation, so it cannot be
        # traversed with select_related. The lead's selected package is a FK.
        leads = Lead.objects.select_related("customer", "plan", "package")
        if status_value != "all":
            leads = leads.filter(status=status_value)
        if self.request.user.role != User.Role.SUPER:
            leads = leads.filter(assigned_sales_person=self.request.user)
        return leads.order_by("-date", "-id")

    def post(self, request, *args, **kwargs):
        serializer = CRMLeadCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        lead = serializer.save()
        post_message(lead, body="Lead created.", author=request.user)
        data = LeadDetailSerializer(lead, context={"request": request}).data
        return Response(Formatter.success(data=data, message="Lead created."), status=201)


class CRMLeadDetail(RetrieveUpdateAPIView):
    """Retrieve or update a lead, limited to its assignee or a super user."""

    serializer_class = LeadDetailSerializer
    permission_classes = [IsSalesOrSuper, IsLeadAssigneeOrSuper]
    lookup_url_kwarg = "lead_id"

    def get_queryset(self):
        return Lead.objects.select_related(
            "customer", "plan", "package", "assigned_sales_person", "event_record"
        ).prefetch_related("plan__packages", "package__contents")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, LEAD_TRACKED_FIELDS)
        lead = serializer.save()
        log_changes(lead, before, LEAD_TRACKED_FIELDS, self.request.user, labels=LEAD_FIELD_LABELS)


class ConvertLeadToEvent(APIView):
    permission_classes = [IsSalesOrSuper, IsLeadAssigneeOrSuper]

    def post(self, request, lead_id):
        lead = get_object_or_404(
            Lead.objects.select_related("customer", "plan", "package"), pk=lead_id
        )
        self.check_object_permissions(request, lead)
        if lead.status != Lead.Status.WON:
            raise ValidationError({"status": "Only a won lead can be converted to an event."})
        event, created = Event.objects.get_or_create(
            lead=lead,
            defaults={
                "customer": lead.customer,
                "plan": lead.plan,
                "package": lead.package,
                "name": f"{lead.customer.name} — {lead.event_type or lead.plan.name}",
                "event_type": lead.event_type,
                "event_date": lead.plan_date,
                "guest_count": lead.guest_count,
                "location": lead.location,
            },
        )
        if created:
            post_message(lead, body=f"Event #{event.id} “{event.name}” created from this lead.", author=request.user)
            post_message(event, body=f"Event created from lead #{lead.id}.", author=request.user)
        return Response(Formatter.success(
            data={
                "id": event.id,
                "name": event.name,
                "event_date": event.event_date.isoformat(),
                "status": event.status,
                "created": created,
            },
            message="Event created from won lead." if created else "This lead already has an event.",
        ), status=201 if created else 200)


class CustomerHistory(APIView):
    permission_classes = [IsSalesOrSuper]

    def get(self, request, customer_id):
        customer = get_object_or_404(Customers, pk=customer_id)
        leads = Lead.objects.filter(customer=customer)
        if request.user.role != User.Role.SUPER:
            leads = leads.filter(assigned_sales_person=request.user)
            if not leads.exists():
                raise PermissionDenied("You can only view customers connected to your assigned leads.")
        invoices = CustomerInvoice.objects.filter(customer=customer).select_related("plan", "package")
        history = [
            {
                "kind": "lead", "id": lead.id, "date": lead.date.isoformat(),
                "status": lead.get_status_display(), "plan": lead.plan.name,
                "package": lead.package.name if lead.package_id else None,
            }
            for lead in leads.select_related("plan", "package").order_by("-date", "-id")
        ] + [
            {
                "kind": "invoice", "id": invoice.id, "date": invoice.date.isoformat(),
                "reference": invoice.reference, "total": str(invoice.total),
                "plan": invoice.plan.name, "package": invoice.package.name if invoice.package_id else None,
            }
            for invoice in invoices.order_by("-date", "-id")
        ] + [
            {
                "kind": "event", "id": event.id, "date": event.created_at.date().isoformat(),
                "name": event.name, "event_date": event.event_date.isoformat(),
                "status": event.get_status_display(),
            }
            for event in (
                Event.objects.filter(customer=customer)
                .filter(lead__assigned_sales_person=request.user)
                .order_by("-created_at", "-id")
                if request.user.role != User.Role.SUPER
                else Event.objects.filter(customer=customer).order_by("-created_at", "-id")
            )
        ]
        history.sort(key=lambda item: (item["date"], item["kind"], item["id"]), reverse=True)
        return Response(Formatter.success(data={
            "customer": {"id": customer.id, "name": customer.name, "phone": customer.phone, "email": customer.email},
            "history": history,
        }))


class MergeCustomers(SuperView):
    def post(self, request):
        try:
            primary = Customers.objects.get(pk=request.data.get("primary_customer_id"))
            duplicate = Customers.objects.get(pk=request.data.get("duplicate_customer_id"))
        except (Customers.DoesNotExist, ValueError, TypeError):
            raise ValidationError("Choose two existing customer records to merge.")
        if primary.pk == duplicate.pk:
            raise ValidationError("A customer cannot be merged into itself.")
        with transaction.atomic():
            Lead.objects.filter(customer=duplicate).update(customer=primary)
            CustomerInvoice.objects.filter(customer=duplicate).update(customer=primary)
            if not primary.email and duplicate.email:
                primary.email = duplicate.email
                primary.save(update_fields=["email"])
            duplicate.delete()
        return Response(Formatter.success(data={"customer_id": primary.id}, message="Customer records merged."))
            
