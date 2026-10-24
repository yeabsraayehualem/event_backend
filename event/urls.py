from django.urls import path

from .views import ProjectDetail, ProjectsList, PublicPlans

urlpatterns = [
    path("plans/", PublicPlans.as_view(), name="public-plans"),
    path("projects/",ProjectsList.as_view(),name="projects-list"),
    path("projects/<int:pk>/", ProjectDetail.as_view()),

]
