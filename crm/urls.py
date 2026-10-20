from django.urls import path
from . import views



urlpatterns = [
    path("sales/dashboard",views.SalesDashboard.as_view(),name="saled-dashboard"),
    path("public/leads/", views.PublicLeadCreate.as_view(), name="public-lead-create"),
    
]
