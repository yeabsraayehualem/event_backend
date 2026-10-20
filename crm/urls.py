from django.urls import path
from . import views



urlpatterns = [
    path("sales/leads/", views.CRMLeads.as_view(), name="sales-leads"),
    path("sales/leads/<int:lead_id>/", views.CRMLeadDetail.as_view(), name="sales-lead-detail"),
    path("sales/dashboard/", views.SalesDashboard.as_view(), name="sales-dashboard"),
    path("sales/dashboard",views.SalesDashboard.as_view(),name="saled-dashboard"),
]
