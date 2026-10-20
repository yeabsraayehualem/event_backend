from django.urls import path

from .views import PublicPlans

urlpatterns = [
    path("plans/", PublicPlans.as_view(), name="public-plans"),
]
