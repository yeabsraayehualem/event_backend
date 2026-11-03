from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from chatter.tracking import log_changes, post_message, snapshot
from event.models import Event
from finance.models import Expense, ExpenseCategory
from hr.models import Employee, ShiftAssignment, Skill
from hr.payroll import active_run_for_shift
from hr.serializers import EmployeeListSerializer, EmployeeSerializer, ShiftSerializer, SkillSerializer
from utils.permissions import CanPayCrew, HRPermission, can_approve_payouts
from utils.rbac import can

EMPLOYEE_TRACKED_FIELDS = [
    "full_name", "phone", "employment_type", "wage_basis", "rate", "job_title", "skills",
    "id_type", "id_number", "id_verified", "payment_account", "active",
]
SHIFT_TRACKED_FIELDS = ["role", "start", "end", "status", "rate", "units"]


def _choices(choices):
    return [{"value": value, "label": label} for value, label in choices]


class HROptions(APIView):
    permission_classes = [HRPermission]

    def get(self, request):
        events = Event.objects.select_related("customer").exclude(status=Event.Status.CANCELLED).order_by("-event_date", "-id")
        employees = Employee.objects.filter(active=True).prefetch_related("skills")
        return Response({
            "skills": list(Skill.objects.values("id", "name")),
            "events": [{"id": e.id, "name": e.name, "event_date": e.event_date.isoformat(), "location": e.location} for e in events],
            "employees": [
                {
                    "id": e.id, "full_name": e.full_name, "job_title": e.job_title, "wage_basis": e.wage_basis,
                    "rate": str(e.rate), "employment_type": e.employment_type, "skills": [s.name for s in e.skills.all()],
                }
                for e in employees
            ],
            "employment_types": _choices(Employee.EmploymentType.choices),
            "wage_bases": _choices(Employee.WageBasis.choices),
            "id_types": _choices(Employee.IdType.choices),
            "shift_statuses": _choices(ShiftAssignment.Status.choices),
            "payment_methods": _choices(Expense.PaymentMethod.choices),
            "can_edit": can(request.user, "crew", "edit"),
            "can_pay": can_approve_payouts(request.user),
        })


class SkillList(ListCreateAPIView):
    serializer_class = SkillSerializer
    permission_classes = [HRPermission]

    def get_queryset(self):
        return Skill.objects.annotate(employee_count=Count("employees", filter=Q(employees__active=True)))


class EmployeeList(ListCreateAPIView):
    permission_classes = [HRPermission]

    def get_serializer_class(self):
        return EmployeeSerializer if self.request.method == "POST" else EmployeeListSerializer

    def get_queryset(self):
        upcoming = Q(shifts__end__gte=timezone.now(), shifts__status__in=ShiftAssignment.BOOKED_STATUSES)
        queryset = Employee.objects.prefetch_related("skills").annotate(upcoming_shifts=Count("shifts", filter=upcoming, distinct=True))
        params = self.request.query_params
        if params.get("skill"):
            queryset = queryset.filter(skills__id=params["skill"])
        for name in ("employment_type", "wage_basis"):
            if params.get(name):
                queryset = queryset.filter(**{name: params[name]})
        if params.get("verified") in {"true", "false"}:
            queryset = queryset.filter(id_verified=params["verified"] == "true")
        if params.get("active") in {"true", "false"}:
            queryset = queryset.filter(active=params["active"] == "true")
        return queryset.distinct()

    def perform_create(self, serializer):
        employee = serializer.save()
        post_message(employee, body=f"{employee.get_employment_type_display()} added to the directory.", author=self.request.user)


class EmployeeDetail(RetrieveUpdateAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [HRPermission]
    queryset = Employee.objects.prefetch_related("skills").select_related("user")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, EMPLOYEE_TRACKED_FIELDS)
        employee = serializer.save()
        log_changes(employee, before, EMPLOYEE_TRACKED_FIELDS, self.request.user, labels={"skills": "Skills", "rate": "Rate"})


class EmployeeIdDocument(APIView):
    """POST a copy of the person's ID (multipart, field `id_document`) or DELETE it."""

    permission_classes = [HRPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        upload = request.FILES.get("id_document")
        if not upload:
            raise ValidationError({"id_document": "Choose a file to upload."})
        if employee.id_document:
            employee.id_document.delete(save=False)
        employee.id_document = upload
        employee.save(update_fields=["id_document"])
        post_message(employee, body="ID copy uploaded.", author=request.user)
        return Response(EmployeeSerializer(employee, context={"request": request}).data)

    def delete(self, request, pk):
        employee = get_object_or_404(Employee, pk=pk)
        if employee.id_document:
            employee.id_document.delete(save=False)
            employee.id_document = ""
            employee.save(update_fields=["id_document"])
            post_message(employee, body="ID copy removed.", author=request.user)
        return Response(EmployeeSerializer(employee, context={"request": request}).data)


class ShiftList(ListCreateAPIView):
    """Crew bookings. Filter with ?event=, ?employee=, ?start_date= and ?end_date= (YYYY-MM-DD)."""

    serializer_class = ShiftSerializer
    permission_classes = [HRPermission]

    def get_queryset(self):
        queryset = ShiftAssignment.objects.select_related("employee", "event", "expense")
        params = self.request.query_params
        if params.get("event"):
            queryset = queryset.filter(event_id=params["event"])
        if params.get("employee"):
            queryset = queryset.filter(employee_id=params["employee"])
        for name, lookup in (("start_date", "end__date__gte"), ("end_date", "start__date__lte")):
            if params.get(name):
                value = parse_date(params[name])
                if not value:
                    raise ValidationError({name: "Use YYYY-MM-DD."})
                queryset = queryset.filter(**{lookup: value})
        return queryset

    def perform_create(self, serializer):
        shift = serializer.save(created_by=self.request.user)
        post_message(shift.employee, body=f"Booked as {shift.role} on {shift.event.name}.", author=self.request.user)


class ShiftDetail(RetrieveUpdateDestroyAPIView):
    serializer_class = ShiftSerializer
    permission_classes = [HRPermission]
    queryset = ShiftAssignment.objects.select_related("employee", "event", "expense")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, SHIFT_TRACKED_FIELDS)
        shift = serializer.save()
        log_changes(shift, before, SHIFT_TRACKED_FIELDS, self.request.user, body=f"Shift on {shift.event.name} updated.", record=shift.employee)

    def perform_destroy(self, shift):
        run = active_run_for_shift(shift.pk)
        if run is not None:
            raise ValidationError({"detail": f"This shift is on {run.reference}. Remove it from that payslip first."})
        if shift.payout:
            raise ValidationError({"detail": f"This shift was paid by {shift.payout.reference}. Delete that expense first."})
        post_message(shift.employee, body=f"Removed from {shift.event.name}.", author=self.request.user)
        shift.delete()


class ShiftPayout(APIView):
    """POST {"payment_method", "date"?} to pay a worked shift. Creates a crew-payout expense on the event."""

    permission_classes = [CanPayCrew]

    @transaction.atomic
    def post(self, request, pk):
        shift = get_object_or_404(ShiftAssignment.objects.select_for_update().select_related("employee", "event"), pk=pk)
        if shift.payout:
            raise ValidationError({"detail": f"Already paid by {shift.payout.reference}."})
        if shift.status != ShiftAssignment.Status.COMPLETED:
            raise ValidationError({"detail": "Mark the shift as worked before paying it."})
        run = active_run_for_shift(shift.pk)
        if run is not None:
            raise ValidationError({"detail": f"This shift is on {run.reference}. It will be paid with that run."})
        if not shift.payable:
            raise ValidationError({"detail": f"{shift.employee.full_name} is on a monthly salary, so this shift is covered by payroll."})
        if shift.amount <= 0:
            raise ValidationError({"detail": "This shift has no amount to pay. Check the rate and days worked."})

        method = request.data.get("payment_method") or Expense.PaymentMethod.BANK_TRANSFER
        if method not in Expense.PaymentMethod.values:
            raise ValidationError({"payment_method": "Choose cash, bank transfer, check or mobile money."})
        date = parse_date(str(request.data.get("date") or "")) or timezone.localdate()
        category = ExpenseCategory.objects.filter(name="Freelance crew").first() or ExpenseCategory.objects.first()

        expense = Expense.objects.create(
            date=date, category=category, source=Expense.Source.CREW_PAYOUT, shift=shift, event=shift.event,
            description=f"{shift.employee.full_name} – {shift.role}", payee=shift.employee.full_name,
            amount=shift.amount, payment_method=method, receipt_number=str(request.data.get("receipt_number", ""))[:60],
            notes=f"{shift.units} × {shift.rate} ({shift.get_wage_basis_display()})", created_by=request.user,
        )
        post_message(expense, body=f"Crew payout for {shift.event.name}.", author=request.user)
        post_message(shift.employee, body=f"Paid {expense.amount:,.2f} for {shift.event.name} ({expense.reference}).", author=request.user)
        shift = ShiftDetail.queryset.get(pk=shift.pk)
        return Response(ShiftSerializer(shift, context={"request": request}).data)
