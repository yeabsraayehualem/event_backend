"""Staff and freelance crew (HR-001) and their assignments to events (HR-002)."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Skill(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Employee(models.Model):
    """Anyone who works events: permanent staff or on-call freelancers (ushers, stagehands, sound…)."""

    class EmploymentType(models.TextChoices):
        PERMANENT = "permanent", "Permanent staff"
        FREELANCE = "freelance", "Freelancer"

    class WageBasis(models.TextChoices):
        MONTHLY = "monthly", "Monthly salary"
        DAILY = "daily", "Day rate"
        PER_EVENT = "per_event", "Per event"

    class IdType(models.TextChoices):
        NATIONAL_ID = "national_id", "National ID (Fayda)"
        KEBELE = "kebele", "Kebele ID"
        PASSPORT = "passport", "Passport"
        DRIVING_LICENSE = "driving_license", "Driving license"

    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, unique=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee",
        help_text="Only for people who sign in to the system.",
    )
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices, default=EmploymentType.FREELANCE)
    wage_basis = models.CharField(max_length=20, choices=WageBasis.choices, default=WageBasis.DAILY)
    rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)],
        help_text="Monthly salary, day rate or per-event fee, depending on the wage basis.",
    )
    job_title = models.CharField(max_length=100, blank=True)
    skills = models.ManyToManyField(Skill, blank=True, related_name="employees")
    id_type = models.CharField("ID type", max_length=20, choices=IdType.choices, blank=True)
    id_number = models.CharField("ID number", max_length=60, blank=True)
    id_document = models.FileField("ID copy", upload_to="employee_ids/", blank=True)
    id_verified = models.BooleanField("ID verified", default=False)
    emergency_contact = models.CharField(max_length=150, blank=True)
    payment_account = models.CharField(max_length=100, blank=True, help_text="Bank account or mobile money number for payouts.")
    hire_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name", "id"]

    def __str__(self):
        return self.full_name


class ShiftAssignment(models.Model):
    """One person booked on one event for a block of time, and what they are owed for it."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Worked"
        NO_SHOW = "no_show", "No-show"
        CANCELLED = "cancelled", "Cancelled"

    # Statuses that keep a person busy for the time slot.
    BOOKED_STATUSES = (Status.SCHEDULED, Status.CONFIRMED, Status.COMPLETED)

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="shifts")
    event = models.ForeignKey("event.Event", on_delete=models.PROTECT, related_name="shifts")
    role = models.CharField(max_length=100, help_text="What they do on this event, e.g. Usher, Sound engineer.")
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    wage_basis = models.CharField(max_length=20, choices=Employee.WageBasis.choices)
    rate = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    units = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("1.00"), validators=[MinValueValidator(0)],
        help_text="Days worked for a day rate; 1 for a per-event fee.",
    )
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="shift_ends_after_start")]

    def __str__(self):
        return f"{self.employee} – {self.event} ({self.role})"

    @property
    def payable(self):
        """Salaried staff are covered by payroll; freelance work is paid per shift."""
        return self.wage_basis != Employee.WageBasis.MONTHLY

    @property
    def amount(self):
        if not self.payable:
            return Decimal("0.00")
        units = Decimal("1.00") if self.wage_basis == Employee.WageBasis.PER_EVENT else self.units
        return (units * self.rate).quantize(Decimal("0.01"))

    @property
    def payout(self):
        return getattr(self, "expense", None)  # reverse one-to-one from finance.Expense

    def overlapping(self):
        """Other live bookings for the same person whose time overlaps this one."""
        return (
            ShiftAssignment.objects.filter(employee_id=self.employee_id, status__in=self.BOOKED_STATUSES, start__lt=self.end, end__gt=self.start)
            .exclude(pk=self.pk)
            .select_related("event")
        )


# ── Payroll ──────────────────────────────────────────────────────────────────────


class PayrollSettings(models.Model):
    """Company-wide payroll rules (one row). Rates are percentages."""

    employee_pension_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("7.00"))
    employer_pension_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("11.00"))
    freelance_withholding_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Withheld from freelancer pay, if your accountant says it applies.",
    )
    tax_table_confirmed = models.BooleanField(
        default=False, help_text="Tick once the accountant has checked the income tax brackets are current.",
    )
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "payroll settings"

    def __str__(self):
        return "Payroll settings"

    @classmethod
    def current(cls):
        settings_row, _ = cls.objects.get_or_create(pk=1)
        return settings_row


class IncomeTaxBracket(models.Model):
    """Monthly employment income tax band: income up to `upper_limit` is taxed at `rate`%."""

    upper_limit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Leave empty for the top band.")
    rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        ordering = [models.F("upper_limit").asc(nulls_last=True)]

    def __str__(self):
        return f"up to {self.upper_limit or '∞'}: {self.rate}%"


def income_tax(monthly_income, brackets):
    """Marginal tax: each slice of income is taxed at its band's rate."""
    tax, lower = Decimal("0.00"), Decimal("0.00")
    for bracket in brackets:
        upper = bracket.upper_limit
        if monthly_income <= lower:
            break
        slice_top = monthly_income if upper is None else min(monthly_income, upper)
        tax += (slice_top - lower) * bracket.rate / Decimal("100")
        if upper is None:
            break
        lower = upper
    return tax.quantize(Decimal("0.01"))


class PayRun(models.Model):
    """One month's pay for everyone: draft → approved → paid."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE_STATUSES = (Status.DRAFT, Status.APPROVED, Status.PAID)

    period = models.DateField(help_text="First day of the month this run pays.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    payment_method = models.CharField(max_length=20, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["period"], condition=~models.Q(status="cancelled"), name="one_live_pay_run_per_month"),
        ]

    @property
    def reference(self):
        return f"PAY-{self.period:%Y-%m}"

    def __str__(self):
        return self.reference


class Payslip(models.Model):
    class Kind(models.TextChoices):
        SALARY = "salary", "Salary"
        FREELANCE = "freelance", "Freelance shifts"

    run = models.ForeignKey(PayRun, on_delete=models.CASCADE, related_name="payslips")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payslips")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    held = models.BooleanField(default=False, help_text="Held payslips are left out when the run is paid.")
    payment_account = models.CharField(max_length=100, blank=True)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    income_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    pension_employee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    pension_employer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    withholding = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["kind", "employee__full_name"]
        constraints = [models.UniqueConstraint(fields=["run", "employee"], name="one_payslip_per_person_per_run")]

    def __str__(self):
        return f"{self.run} – {self.employee}"

    @property
    def employer_cost(self):
        return self.gross + self.pension_employer

    def recalculate(self, rules=None, brackets=None):
        rules = rules or PayrollSettings.current()
        lines = list(self.lines.all())
        earnings = sum((line.amount for line in lines if line.kind == PayslipLine.Kind.EARNING), Decimal("0.00"))
        manual = sum((line.amount for line in lines if line.kind == PayslipLine.Kind.DEDUCTION), Decimal("0.00"))
        pct = lambda base, rate: (base * rate / Decimal("100")).quantize(Decimal("0.01"))
        self.gross, self.other_deductions = earnings, manual
        if self.kind == self.Kind.SALARY:
            brackets = brackets if brackets is not None else list(IncomeTaxBracket.objects.all())
            self.income_tax = income_tax(earnings, brackets)
            self.pension_employee = pct(self.basic_salary, rules.employee_pension_rate)
            self.pension_employer = pct(self.basic_salary, rules.employer_pension_rate)
            self.withholding = Decimal("0.00")
        else:
            self.income_tax = self.pension_employee = self.pension_employer = Decimal("0.00")
            self.withholding = pct(earnings, rules.freelance_withholding_rate)
        self.net = earnings - self.income_tax - self.pension_employee - self.withholding - manual
        self.save()


class PayslipLine(models.Model):
    class Kind(models.TextChoices):
        EARNING = "earning", "Earning"
        DEDUCTION = "deduction", "Deduction"

    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.EARNING)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    shift = models.ForeignKey(ShiftAssignment, on_delete=models.PROTECT, null=True, blank=True, related_name="payslip_lines")
    is_basic = models.BooleanField(default=False, help_text="The monthly salary line; pension is worked out from it.")

    class Meta:
        ordering = ["-is_basic", "kind", "id"]

    def __str__(self):
        return self.description
