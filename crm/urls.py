from django.urls import path
from . import views



urlpatterns = [
    path("sales/dashboard/", views.SalesDashboard.as_view(), name="sales-dashboard"),
    path("sales/dashboard",views.SalesDashboard.as_view(),name="saled-dashboard"),
]
