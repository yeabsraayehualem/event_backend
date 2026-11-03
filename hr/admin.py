from django.contrib import admin

from hr.models import Employee, ShiftAssignment, Skill

admin.site.register(Skill)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "employment_type", "wage_basis", "rate", "id_verified", "active")
    list_filter = ("employment_type", "wage_basis", "id_verified", "active", "skills")
    search_fields = ("full_name", "phone", "id_number")


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "event", "role", "start", "end", "status")
    list_filter = ("status",)


from hr.models import IncomeTaxBracket, PayrollSettings, PayRun, Payslip, PayslipLine

admin.site.register(PayrollSettings)
admin.site.register(IncomeTaxBracket)


class PayslipLineInline(admin.TabularInline):
    model = PayslipLine
    extra = 0


@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ("run", "employee", "kind", "gross", "net", "held")
    inlines = [PayslipLineInline]


@admin.register(PayRun)
class PayRunAdmin(admin.ModelAdmin):
    list_display = ("reference", "period", "status", "paid_on")
