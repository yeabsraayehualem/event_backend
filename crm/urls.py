from django.urls import path
from . import views



urlpatterns = [
    path("sales/leads/", views.CRMLeads.as_view(), name="sales-leads"),
    path("sales/lead-form-options/", views.LeadFormOptions.as_view(), name="sales-lead-form-options"),
    path("sales/leads/<int:lead_id>/", views.CRMLeadDetail.as_view(), name="sales-lead-detail"),
    path("sales/leads/<int:lead_id>/convert/", views.ConvertLeadToEvent.as_view(), name="sales-lead-convert-event"),
    path("sales/dashboard/", views.SalesDashboard.as_view(), name="sales-dashboard"),
    path("customers/<int:customer_id>/history/", views.CustomerHistory.as_view(), name="customer-history"),
    path("customers/merge/", views.MergeCustomers.as_view(), name="customer-merge"),
    path("sales/dashboard",views.SalesDashboard.as_view(),name="saled-dashboard"),
]
