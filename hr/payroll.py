"""Monthly pay runs: salaries for staff, and every worked-but-unpaid shift for freelancers.

A run is generated as a draft, adjusted per payslip (hold, bonus, deduction, drop a shift),
approved by finance, then marked paid. Paying it records the expenses: salaries as overhead,
freelance shifts as costs on their events.
"""

import calendar
import csv
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from chatter.tracking import post_message
from finance.models import Expense, ExpenseCategory
from hr.models import (
    Employee, IncomeTaxBracket, PayrollSettings, PayRun, Payslip, PayslipLine, ShiftAssignment,
)
from utils.permissions import PayrollPermission, can_approve_payroll

CENT = Decimal("0.01")


def require_approver(user):
    if not can_approve_payroll(user):
        raise PermissionDenied("Only finance, admins or super users can do this.")


def active_run_for_shift(shift_id):
    """The live pay run (draft, approved or paid) a shift is already on, if any."""
    line = (
        PayslipLine.objects.filter(shift_id=shift_id, payslip__run__status__in=PayRun.ACTIVE_STATUSES)
        .select_related("payslip__run").first()
    )
    return line.payslip.run if line else None


def month_bounds(period):
    first = period.replace(day=1)
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def unpaid_shifts(last_day):
    """Worked freelance shifts up to `last_day` that are neither paid nor on a live run."""
    return (
        ShiftAssignment.objects.filter(status=ShiftAssignment.Status.COMPLETED, start__date__lte=last_day, expense__isnull=True)
        .exclude(wage_basis=Employee.WageBasis.MONTHLY)
        .exclude(payslip_lines__payslip__run__status__in=PayRun.ACTIVE_STATUSES)
        .select_related("employee", "event")
        .order_by("start")
    )


def shift_line_text(shift):
    return f"{shift.event.name} – {shift.role} ({timezone.localtime(shift.start):%d %b})"


def fill_run(run):
    """Add whatever the run is missing: salaried staff without a payslip, and newly worked shifts.

    Safe to call again on a draft; existing payslips and manual changes are kept.
    """
    first, last = month_bounds(run.period)
    days_in_month = (last - first).days + 1
    existing = {slip.employee_id: slip for slip in run.payslips.all()}
    touched = set()

    salaried = Employee.objects.filter(active=True, wage_basis=Employee.WageBasis.MONTHLY, rate__gt=0)
    for person in salaried:
        if person.id in existing:
            continue
        start = max(first, person.hire_date) if person.hire_date else first
        if start > last:
            continue
        days = (last - start).days + 1
        basic = person.rate if days == days_in_month else (person.rate * days / days_in_month).quantize(CENT)
        slip = Payslip.objects.create(run=run, employee=person, kind=Payslip.Kind.SALARY, payment_account=person.payment_account, basic_salary=basic)
        text = "Monthly salary" if days == days_in_month else f"Salary for {days} of {days_in_month} days (started {start:%d %b})"
        PayslipLine.objects.create(payslip=slip, kind=PayslipLine.Kind.EARNING, description=text, amount=basic, is_basic=True)
        existing[person.id] = slip
        touched.add(slip.id)

    by_person = defaultdict(list)
    for shift in unpaid_shifts(last):
        if shift.amount > 0:
            by_person[shift.employee].append(shift)
    for person, shifts in by_person.items():
        slip = existing.get(person.id)
        if slip is None:
            slip = Payslip.objects.create(run=run, employee=person, kind=Payslip.Kind.FREELANCE, payment_account=person.payment_account)
            existing[person.id] = slip
        PayslipLine.objects.bulk_create([
            PayslipLine(payslip=slip, kind=PayslipLine.Kind.EARNING, description=shift_line_text(shift), amount=shift.amount, shift=shift)
            for shift in shifts
        ])
        touched.add(slip.id)

    recalculate_run(run)
    return len(touched)


def recalculate_run(run):
    rules, brackets = PayrollSettings.current(), list(IncomeTaxBracket.objects.all())
    for slip in run.payslips.prefetch_related("lines"):
        slip.recalculate(rules, brackets)


def run_totals(run):
    included = run.payslips.filter(held=False)
    sums = included.aggregate(
        gross=Sum("gross"), net=Sum("net"), income_tax=Sum("income_tax"), pension_employee=Sum("pension_employee"),
        pension_employer=Sum("pension_employer"), withholding=Sum("withholding"), other_deductions=Sum("other_deductions"),
    )
    totals = {key: (value or Decimal("0.00")).quantize(CENT) for key, value in sums.items()}
    totals["employer_cost"] = totals["gross"] + totals["pension_employer"]
    return {
        **{key: str(value) for key, value in totals.items()},
        "people": included.count(),
        "held": run.payslips.filter(held=True).count(),
    }


def run_warnings(run, rules):
    included = [slip for slip in run.payslips.all() if not slip.held]
    warnings = []
    if any(slip.kind == Payslip.Kind.SALARY for slip in included) and not rules.tax_table_confirmed:
        warnings.append({"code": "tax_table", "message": "The income tax table hasn't been confirmed by your accountant, so this run can't be approved yet."})
    missing = [slip.employee.full_name for slip in included if not slip.payment_account.strip()]
    if missing:
        warnings.append({"code": "accounts", "message": f"No bank or mobile money account for: {', '.join(missing)}. They'll be missing from the bank file."})
    negative = [slip.employee.full_name for slip in included if slip.net < 0]
    if negative:
        warnings.append({"code": "negative", "message": f"Deductions exceed pay for: {', '.join(negative)}."})
    return warnings


# ── Serializers ──────────────────────────────────────────────────────────────────


class PayslipLineSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="shift.event.name", read_only=True, allow_null=True)

    class Meta:
        model = PayslipLine
        fields = ["id", "kind", "description", "amount", "shift", "event_name", "is_basic"]
        read_only_fields = ["id", "shift", "event_name", "is_basic"]


class PayslipSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_phone = serializers.CharField(source="employee.phone", read_only=True)
    job_title = serializers.CharField(source="employee.job_title", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    employer_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    lines = PayslipLineSerializer(many=True, read_only=True)

    class Meta:
        model = Payslip
        fields = [
            "id", "employee", "employee_name", "employee_phone", "job_title", "kind", "kind_label", "held",
            "payment_account", "basic_salary", "gross", "income_tax", "pension_employee", "pension_employer",
            "withholding", "other_deductions", "net", "employer_cost", "notes", "lines",
        ]
        read_only_fields = [name for name in fields if name not in {"held", "payment_account", "notes"}]


class PayRunListSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = PayRun
        fields = ["id", "reference", "period", "status", "status_label", "paid_on", "totals", "created_at"]

    def get_totals(self, run):
        return run_totals(run)


class PayRunSerializer(PayRunListSerializer):
    payslips = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()
    rules = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()

    class Meta(PayRunListSerializer.Meta):
        fields = [
            *PayRunListSerializer.Meta.fields, "payment_method", "notes", "approved_by_name", "approved_at",
            "payslips", "warnings", "rules", "can_approve",
        ]

    def _slips(self, run):
        return run.payslips.select_related("employee").prefetch_related("lines__shift__event")

    def get_payslips(self, run):
        return PayslipSerializer(self._slips(run), many=True).data

    def get_warnings(self, run):
        return run_warnings(run, PayrollSettings.current()) if run.status in {PayRun.Status.DRAFT, PayRun.Status.APPROVED} else []

    def get_rules(self, run):
        return settings_payload(PayrollSettings.current())

    def get_approved_by_name(self, run):
        user = run.approved_by
        return (user.get_full_name() or user.phone) if user else None

    def get_can_approve(self, run):
        request = self.context.get("request")
        return bool(request and can_approve_payroll(request.user))


def settings_payload(rules):
    return {
        "employee_pension_rate": str(rules.employee_pension_rate),
        "employer_pension_rate": str(rules.employer_pension_rate),
        "freelance_withholding_rate": str(rules.freelance_withholding_rate),
        "tax_table_confirmed": rules.tax_table_confirmed,
        "confirmed_at": rules.confirmed_at.isoformat() if rules.confirmed_at else None,
        "confirmed_by": (rules.confirmed_by.get_full_name() or rules.confirmed_by.phone) if rules.confirmed_by else None,
        "brackets": [{"upper_limit": None if b.upper_limit is None else str(b.upper_limit), "rate": str(b.rate)} for b in IncomeTaxBracket.objects.all()],
    }


# ── Views ────────────────────────────────────────────────────────────────────────


def _run_response(request, run):
    run = PayRun.objects.select_related("approved_by").get(pk=run.pk)
    return Response(PayRunSerializer(run, context={"request": request}).data)


def _draft_run(pk, lock=False):
    queryset = PayRun.objects.select_for_update() if lock else PayRun.objects
    run = get_object_or_404(queryset, pk=pk)
    if run.status != PayRun.Status.DRAFT:
        raise ValidationError({"detail": f"{run.reference} is {run.get_status_display().lower()}. Reopen it as a draft to make changes."})
    return run


class PayRunList(APIView):
    """GET the pay runs; POST {"period": "2026-11"} (or a full date) to generate that month's draft."""

    permission_classes = [PayrollPermission]

    def get(self, request):
        runs = PayRun.objects.all()
        return Response({
            "runs": PayRunListSerializer(runs, many=True).data,
            "rules": settings_payload(PayrollSettings.current()),
            "can_approve": can_approve_payroll(request.user),
        })

    @transaction.atomic
    def post(self, request):
        raw = str(request.data.get("period", "")).strip()
        period = parse_date(f"{raw}-01" if len(raw) == 7 else raw)
        if not period:
            raise ValidationError({"period": "Choose the month to pay, e.g. 2026-11."})
        period = period.replace(day=1)
        existing = PayRun.objects.filter(period=period).exclude(status=PayRun.Status.CANCELLED).first()
        if existing:
            raise ValidationError({"detail": f"{existing.reference} already exists ({existing.get_status_display().lower()}).", "run_id": existing.id})
        try:
            with transaction.atomic():
                run = PayRun.objects.create(period=period, created_by=request.user)
        except IntegrityError:
            raise ValidationError({"detail": "A pay run for that month was just created by someone else."})
        if not fill_run(run):
            raise ValidationError({"detail": f"Nobody to pay for {period:%B %Y}: no salaried staff and no worked, unpaid shifts."})
        return _run_response(request, run)


class PayRunDetail(APIView):
    permission_classes = [PayrollPermission]

    def get(self, request, pk):
        return _run_response(request, get_object_or_404(PayRun, pk=pk))

    def patch(self, request, pk):
        run = get_object_or_404(PayRun, pk=pk)
        if "notes" in request.data:
            run.notes = str(request.data["notes"])[:2000]
            run.save(update_fields=["notes"])
        return _run_response(request, run)


class PayRunTransition(APIView):
    """POST {"action": "refresh" | "approve" | "reopen" | "pay" | "cancel", "paid_on"?, "payment_method"?}."""

    permission_classes = [PayrollPermission]

    @transaction.atomic
    def post(self, request, pk):
        run = get_object_or_404(PayRun.objects.select_for_update(), pk=pk)
        action = request.data.get("action")
        handler = getattr(self, f"_{action}", None) if action in {"refresh", "approve", "reopen", "pay", "cancel"} else None
        if handler is None:
            raise ValidationError({"action": "Choose refresh, approve, reopen, pay or cancel."})
        handler(request, run)
        return _run_response(request, run)

    @staticmethod
    def _expect(run, *statuses):
        if run.status not in statuses:
            raise ValidationError({"detail": f"{run.reference} is {run.get_status_display().lower()}."})

    def _refresh(self, request, run):
        self._expect(run, PayRun.Status.DRAFT)
        fill_run(run)

    def _approve(self, request, run):
        require_approver(request.user)
        self._expect(run, PayRun.Status.DRAFT)
        recalculate_run(run)
        if not run.payslips.filter(held=False).exists():
            raise ValidationError({"detail": "Every payslip is on hold, so there's nothing to approve."})
        blocking = [w for w in run_warnings(run, PayrollSettings.current()) if w["code"] in {"tax_table", "negative"}]
        if blocking:
            raise ValidationError({"detail": " ".join(w["message"] for w in blocking)})
        run.status, run.approved_by, run.approved_at = PayRun.Status.APPROVED, request.user, timezone.now()
        run.save(update_fields=["status", "approved_by", "approved_at"])

    def _reopen(self, request, run):
        require_approver(request.user)
        self._expect(run, PayRun.Status.APPROVED)
        run.status, run.approved_by, run.approved_at = PayRun.Status.DRAFT, None, None
        run.save(update_fields=["status", "approved_by", "approved_at"])

    def _cancel(self, request, run):
        self._expect(run, PayRun.Status.DRAFT, PayRun.Status.APPROVED)
        if run.status == PayRun.Status.APPROVED:
            require_approver(request.user)
        run.status = PayRun.Status.CANCELLED
        run.save(update_fields=["status"])

    def _pay(self, request, run):
        require_approver(request.user)
        self._expect(run, PayRun.Status.APPROVED)
        method = request.data.get("payment_method") or Expense.PaymentMethod.BANK_TRANSFER
        if method not in Expense.PaymentMethod.values:
            raise ValidationError({"payment_method": "Choose cash, bank transfer, check or mobile money."})
        paid_on = parse_date(str(request.data.get("paid_on") or "")) or timezone.localdate()

        # Held people roll over: drop their payslips so their shifts are free for next month.
        run.payslips.filter(held=True).delete()
        salaries = ExpenseCategory.objects.filter(name="Salaries").first() or ExpenseCategory.objects.first()
        crew = ExpenseCategory.objects.filter(name="Freelance crew").first() or salaries
        month = f"{run.period:%B %Y}"
        common = {"date": paid_on, "payment_method": method, "created_by": request.user, "receipt_number": run.reference}

        for slip in run.payslips.select_related("employee").prefetch_related("lines__shift__event"):
            person = slip.employee.full_name
            if slip.kind == Payslip.Kind.SALARY:
                Expense.objects.create(
                    **common, category=salaries, source=Expense.Source.PAYROLL, payslip=slip, payee=person,
                    description=f"Salary {month} – {person}", amount=slip.employer_cost,
                    notes=f"Gross {slip.gross}, income tax {slip.income_tax}, pension {slip.pension_employee} + {slip.pension_employer} employer, net paid {slip.net}.",
                )
                continue
            extra = Decimal("0.00")
            for line in slip.lines.all():
                if line.kind != PayslipLine.Kind.EARNING:
                    continue
                if line.shift_id:
                    Expense.objects.create(
                        **common, category=crew, source=Expense.Source.CREW_PAYOUT, payslip=slip, shift=line.shift,
                        event=line.shift.event, payee=person, description=f"{person} – {line.shift.role}", amount=line.amount,
                    )
                else:
                    extra += line.amount
            if extra:
                Expense.objects.create(
                    **common, category=crew, source=Expense.Source.PAYROLL, payslip=slip, payee=person,
                    description=f"{person} – additions {month}", amount=extra,
                )
            post_message(slip.employee, body=f"Paid {slip.net:,.2f} in {run.reference}.", author=request.user)

        run.status, run.paid_on, run.payment_method = PayRun.Status.PAID, paid_on, method
        run.save(update_fields=["status", "paid_on", "payment_method"])


class PayslipDetail(APIView):
    """PATCH {"held", "notes", "payment_account"} or DELETE to take the person off a draft run."""

    permission_classes = [PayrollPermission]

    def patch(self, request, pk):
        slip = get_object_or_404(Payslip, pk=pk)
        run = _draft_run(slip.run_id)
        serializer = PayslipSerializer(slip, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return _run_response(request, run)

    def delete(self, request, pk):
        slip = get_object_or_404(Payslip, pk=pk)
        run = _draft_run(slip.run_id)
        slip.delete()
        return _run_response(request, run)


class PayslipLines(APIView):
    """POST {"kind": "earning" | "deduction", "description", "amount"} to add a bonus or deduction."""

    permission_classes = [PayrollPermission]

    @transaction.atomic
    def post(self, request, pk):
        slip = get_object_or_404(Payslip, pk=pk)
        run = _draft_run(slip.run_id)
        serializer = PayslipLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(payslip=slip)
        slip.recalculate()
        return _run_response(request, run)


class PayslipLineDetail(APIView):
    """PATCH {"amount", "description"} (e.g. unpaid leave on the salary line) or DELETE a line."""

    permission_classes = [PayrollPermission]

    @transaction.atomic
    def patch(self, request, pk, line_pk):
        line = get_object_or_404(PayslipLine, pk=line_pk, payslip_id=pk)
        run = _draft_run(line.payslip.run_id)
        if line.shift_id and "amount" in request.data:
            raise ValidationError({"amount": "Shift pay comes from the shift. Change the days or rate on the event schedule."})
        serializer = PayslipLineSerializer(line, data={k: v for k, v in request.data.items() if k in {"amount", "description"}}, partial=True)
        serializer.is_valid(raise_exception=True)
        line = serializer.save()
        if line.is_basic:
            line.payslip.basic_salary = line.amount
            line.payslip.save(update_fields=["basic_salary"])
        line.payslip.recalculate()
        return _run_response(request, run)

    @transaction.atomic
    def delete(self, request, pk, line_pk):
        line = get_object_or_404(PayslipLine, pk=line_pk, payslip_id=pk)
        run = _draft_run(line.payslip.run_id)
        if line.is_basic:
            raise ValidationError({"detail": "Take the person off the run instead of removing their salary."})
        slip = line.payslip
        line.delete()
        if not slip.lines.exists():
            slip.delete()
        else:
            slip.recalculate()
        return _run_response(request, run)


class PayRunBankFile(APIView):
    """CSV of who to pay and how much, for the bank's bulk transfer upload."""

    permission_classes = [PayrollPermission]

    def get(self, request, pk):
        run = get_object_or_404(PayRun, pk=pk)
        if run.status not in {PayRun.Status.APPROVED, PayRun.Status.PAID}:
            raise ValidationError({"detail": "Approve the run before exporting the bank file."})
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{run.reference}-bank-transfers.csv"'
        response.write("﻿")  # so Excel opens Amharic names correctly
        writer = csv.writer(response)
        writer.writerow(["No", "Name", "Phone", "Account", "Amount", "Narration"])
        slips = run.payslips.filter(held=False, net__gt=0).select_related("employee").order_by("employee__full_name")
        for index, slip in enumerate(slips, start=1):
            writer.writerow([index, slip.employee.full_name, slip.employee.phone, slip.payment_account, f"{slip.net:.2f}", f"{run.reference} {slip.get_kind_display()}"])
        return response


class PayrollRules(APIView):
    """GET the payroll rules; PATCH rates, the tax brackets, or confirm the tax table (approvers only)."""

    permission_classes = [PayrollPermission]

    def get(self, request):
        return Response(settings_payload(PayrollSettings.current()))

    @transaction.atomic
    def patch(self, request):
        require_approver(request.user)
        rules = PayrollSettings.current()
        for name in ("employee_pension_rate", "employer_pension_rate", "freelance_withholding_rate"):
            if name in request.data:
                try:
                    value = Decimal(str(request.data[name]))
                except InvalidOperation:
                    raise ValidationError({name: "Enter a percentage."}) from None
                if not Decimal(0) <= value <= Decimal(100):
                    raise ValidationError({name: "Use a percentage between 0 and 100."})
                setattr(rules, name, value)
        if "brackets" in request.data:
            rows = request.data["brackets"] or []
            try:
                parsed = [(None if row.get("upper_limit") in (None, "") else Decimal(str(row["upper_limit"])), Decimal(str(row["rate"]))) for row in rows]
            except (InvalidOperation, KeyError, TypeError, AttributeError):
                raise ValidationError({"brackets": "Each band needs an upper limit (empty for the top band) and a rate."}) from None
            limits = [upper for upper, _ in parsed if upper is not None]
            if limits != sorted(limits) or len(set(limits)) != len(limits) or sum(upper is None for upper, _ in parsed) != 1 or parsed[-1][0] is not None:
                raise ValidationError({"brackets": "List bands from lowest to highest, ending with one open top band."})
            IncomeTaxBracket.objects.all().delete()
            IncomeTaxBracket.objects.bulk_create([IncomeTaxBracket(upper_limit=upper, rate=rate) for upper, rate in parsed])
            rules.tax_table_confirmed = False  # a changed table needs confirming again
        if request.data.get("tax_table_confirmed") is True:
            rules.tax_table_confirmed, rules.confirmed_by, rules.confirmed_at = True, request.user, timezone.now()
        elif request.data.get("tax_table_confirmed") is False:
            rules.tax_table_confirmed, rules.confirmed_by, rules.confirmed_at = False, None, None
        rules.save()
        # Drafts follow the new rules straight away.
        for run in PayRun.objects.filter(status=PayRun.Status.DRAFT):
            recalculate_run(run)
        return Response(settings_payload(rules))
