from django.urls import path 
from . import views

urlpatterns = [
    path("public/leads/", views.PublicLeadCreate.as_view(), name="public-lead-create"),
    path("plans/",views.PlanListView.as_view(),name="plans-list")

]