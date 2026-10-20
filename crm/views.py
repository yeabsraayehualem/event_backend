from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from rest_framework.generics import ListAPIView
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from crm.models import Lead
from crm.serializers import LeadsSerializer
from utils.formatter import Formatter
from utils.permissions import IsSalesOrSuper
from utils.views import SalesView


User = get_user_model()
ACTIVE_STATUSES = [Lead.Status.LEAD, Lead.Status.CONTACTED, Lead.Status.NEGOTIATION]


class SalesDashboard(SalesView):
    """CRM summary scoped to all leads for super users and owned leads for sales."""

    def get(self, request, *args, **kwargs):
        is_super = request.user.role == User.Role.SUPER
        leads = Lead.objects.all() if is_super else Lead.objects.filter(assigned_sales_person=request.user)
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






class CRMLeads(ListAPIView):
    """List leads for a status, scoped to the current sales user."""

    serializer_class = LeadsSerializer
    permission_classes = [IsSalesOrSuper]

    def get_queryset(self):
        status_value = self.request.query_params.get("status", Lead.Status.LEAD)
        valid_statuses = {value for value, _label in Lead.Status.choices}
        if status_value not in valid_statuses:
            raise ValidationError({
                "status": f"Choose one of: {', '.join(sorted(valid_statuses))}."
            })

        # Plan has a reverse one-to-many `packages` relation, so it cannot be
        # traversed with select_related. The lead's selected package is a FK.
        leads = Lead.objects.select_related("customer", "plan", "package").filter(
            status=status_value
        )
        if self.request.user.role != User.Role.SUPER:
            leads = leads.filter(assigned_sales_person=self.request.user)
        return leads.order_by("-date", "-id")
            
