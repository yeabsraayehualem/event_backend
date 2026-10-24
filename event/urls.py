from django.urls import path

from .views import ProjectsList, PublicPlans

urlpatterns = [
    path("plans/", PublicPlans.as_view(), name="public-plans"),
    path("projects/",ProjectsList.as_view(),name="projects-list"),
]
