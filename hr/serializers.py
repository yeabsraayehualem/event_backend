from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from event.models import Event
from hr.models import Employee, ShiftAssignment, Skill


def _file_url(request, field):
    if not field:
        return None
    return request.build_absolute_uri(field.url) if request else field.url


def _payout(shift):
    expense = shift.payout
    return {"id": expense.id, "reference": expense.reference, "date": expense.date.isoformat()} if expense else None


class SkillSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Skill
        fields = ["id", "name", "employee_count"]


class EmployeeListSerializer(serializers.ModelSerializer):
    employment_type_label = serializers.CharField(source="get_employment_type_display", read_only=True)
    wage_basis_label = serializers.CharField(source="get_wage_basis_display", read_only=True)
    skills = serializers.SerializerMethodField()
    upcoming_shifts = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Employee
        fields = [
            "id", "full_name", "phone", "job_title", "employment_type", "employment_type_label", "wage_basis",
            "wage_basis_label", "rate", "skills", "id_verified", "active", "upcoming_shifts",
        ]

    def get_skills(self, employee):
        return [{"id": skill.id, "name": skill.name} for skill in employee.skills.all()]


class EmployeeSerializer(EmployeeListSerializer):
    skill_ids = serializers.PrimaryKeyRelatedField(source="skills", queryset=Skill.objects.all(), many=True, required=False)
    id_type_label = serializers.CharField(source="get_id_type_display", read_only=True)
    id_document_url = serializers.SerializerMethodField()
    user_phone = serializers.CharField(source="user.phone", read_only=True, allow_null=True)
    shifts = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()

    class Meta(EmployeeListSerializer.Meta):
        fields = [
            *EmployeeListSerializer.Meta.fields, "skill_ids", "id_type", "id_type_label", "id_number", "id_document_url",
            "emergency_contact", "payment_account", "hire_date", "notes", "user", "user_phone", "shifts", "totals",
        ]
        extra_kwargs = {"user": {"required": False, "allow_null": True}}

    def get_id_document_url(self, employee):
        return _file_url(self.context.get("request"), employee.id_document)

    def get_shifts(self, employee):
        return [
            {
                "id": shift.id, "event_id": shift.event_id, "event_name": shift.event.name, "role": shift.role,
                "start": shift.start.isoformat(), "end": shift.end.isoformat(), "status": shift.status,
                "status_label": shift.get_status_display(), "amount": str(shift.amount), "payout": _payout(shift),
            }
            for shift in employee.shifts.select_related("event", "expense").order_by("-start")[:50]
        ]

    def get_totals(self, employee):
        worked = employee.shifts.filter(status=ShiftAssignment.Status.COMPLETED)
        paid = worked.filter(expense__isnull=False).aggregate(value=Sum("expense__amount"))["value"] or Decimal("0.00")
        return {
            "events_worked": worked.values("event").distinct().count(),
            "no_shows": employee.shifts.filter(status=ShiftAssignment.Status.NO_SHOW).count(),
            "paid_total": f"{paid:.2f}",
        }

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter the person's name.")
        return value

    def validate(self, attrs):
        basis = attrs.get("wage_basis", getattr(self.instance, "wage_basis", None))
        kind = attrs.get("employment_type", getattr(self.instance, "employment_type", None))
        if kind == Employee.EmploymentType.FREELANCE and basis == Employee.WageBasis.MONTHLY:
            raise serializers.ValidationError({"wage_basis": "Freelancers are paid a day rate or per event, not a monthly salary."})
        return attrs


class ShiftSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_phone = serializers.CharField(source="employee.phone", read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True)
    event_date = serializers.DateField(source="event.event_date", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    wage_basis_label = serializers.CharField(source="get_wage_basis_display", read_only=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    payable = serializers.BooleanField(read_only=True)
    payout = serializers.SerializerMethodField()
    pay_run = serializers.SerializerMethodField()
    conflicts = serializers.SerializerMethodField()
    allow_conflict = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = ShiftAssignment
        fields = [
            "id", "employee", "employee_name", "employee_phone", "event", "event_name", "event_date", "role",
            "start", "end", "status", "status_label", "wage_basis", "wage_basis_label", "rate", "units", "amount",
            "payable", "notes", "payout", "pay_run", "conflicts", "allow_conflict",
        ]
        extra_kwargs = {
            "employee": {"queryset": Employee.objects.filter(active=True)},
            "event": {"queryset": Event.objects.exclude(status=Event.Status.CANCELLED)},
            "role": {"required": False},
            "wage_basis": {"required": False},
            "rate": {"required": False},
            "units": {"required": False},
        }

    def get_payout(self, shift):
        return _payout(shift)

    def get_pay_run(self, shift):
        from hr.payroll import active_run_for_shift

        run = active_run_for_shift(shift.pk)
        return {"id": run.id, "reference": run.reference, "status": run.status} if run else None

    def get_conflicts(self, shift):
        if shift.status not in ShiftAssignment.BOOKED_STATUSES:
            return []
        return [_conflict(other) for other in shift.overlapping()]

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and instance.payout:
            raise serializers.ValidationError(f"This shift was paid by {instance.payout.reference}, so it can't change. Delete that expense first.")
        if instance is not None:
            from hr.payroll import active_run_for_shift

            run = active_run_for_shift(instance.pk)
            if run is not None:
                raise serializers.ValidationError(f"This shift is on {run.reference}. Remove it from that payslip first.")
        if instance is not None and "employee" in attrs and attrs["employee"].pk != instance.employee_id:
            raise serializers.ValidationError({"employee": "Cancel this shift and book the other person instead."})
        if instance is not None and "event" in attrs and attrs["event"].pk != instance.event_id:
            raise serializers.ValidationError({"event": "A shift can't move to another event."})

        current = lambda name: attrs.get(name, getattr(instance, name, None))
        employee, start, end = current("employee"), current("start"), current("end")
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "The shift must end after it starts."})

        if instance is None:
            # New bookings copy the person's current pay terms, so later rate changes don't rewrite history.
            attrs.setdefault("wage_basis", employee.wage_basis)
            attrs.setdefault("rate", employee.rate)
            attrs.setdefault("role", employee.job_title or next((skill.name for skill in employee.skills.all()), "") or "Crew")
            if "units" not in attrs:
                attrs["units"] = Decimal(_days_spanned(start, end)) if attrs["wage_basis"] == Employee.WageBasis.DAILY else Decimal("1.00")

        status = current("status") or ShiftAssignment.Status.SCHEDULED
        if status in ShiftAssignment.BOOKED_STATUSES and not attrs.pop("allow_conflict", False):
            probe = ShiftAssignment(pk=getattr(instance, "pk", None), employee=employee, start=start, end=end)
            clashes = list(probe.overlapping())
            if clashes:
                raise serializers.ValidationError({
                    "detail": f"{employee.full_name} is already booked then: "
                              + "; ".join(f"{c.event.name} ({c.role})" for c in clashes) + ".",
                    "conflicts": [_conflict(c) for c in clashes],
                })
        attrs.pop("allow_conflict", None)
        return attrs


def _conflict(shift):
    return {"id": shift.id, "event_id": shift.event_id, "event_name": shift.event.name, "role": shift.role,
            "start": shift.start.isoformat(), "end": shift.end.isoformat()}


def _days_spanned(start, end):
    first, last = timezone.localtime(start).date(), timezone.localtime(end).date()
    return max((last - first).days + 1, 1)
