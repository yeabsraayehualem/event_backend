from django.urls import path

from hr import views

urlpatterns = [
    path("options/", views.HROptions.as_view(), name="hr-options"),
    path("skills/", views.SkillList.as_view(), name="skill-list"),
    path("employees/", views.EmployeeList.as_view(), name="employee-list"),
    path("employees/<int:pk>/", views.EmployeeDetail.as_view(), name="employee-detail"),
    path("employees/<int:pk>/id-document/", views.EmployeeIdDocument.as_view(), name="employee-id-document"),
    path("shifts/", views.ShiftList.as_view(), name="shift-list"),
    path("shifts/<int:pk>/", views.ShiftDetail.as_view(), name="shift-detail"),
    path("shifts/<int:pk>/payout/", views.ShiftPayout.as_view(), name="shift-payout"),
]

from hr import payroll

urlpatterns += [
    path("payroll/rules/", payroll.PayrollRules.as_view(), name="payroll-rules"),
    path("pay-runs/", payroll.PayRunList.as_view(), name="pay-run-list"),
    path("pay-runs/<int:pk>/", payroll.PayRunDetail.as_view(), name="pay-run-detail"),
    path("pay-runs/<int:pk>/transition/", payroll.PayRunTransition.as_view(), name="pay-run-transition"),
    path("pay-runs/<int:pk>/bank-file/", payroll.PayRunBankFile.as_view(), name="pay-run-bank-file"),
    path("payslips/<int:pk>/", payroll.PayslipDetail.as_view(), name="payslip-detail"),
    path("payslips/<int:pk>/lines/", payroll.PayslipLines.as_view(), name="payslip-lines"),
    path("payslips/<int:pk>/lines/<int:line_pk>/", payroll.PayslipLineDetail.as_view(), name="payslip-line"),
]
