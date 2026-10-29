from django.urls import path

from . import catalog
from .views import EventOptions, ProjectAssigneeOptions, ProjectDetail, ProjectTaskDetail, ProjectTasks, ProjectsList, PublicPlans

urlpatterns = [
    path("plans/", PublicPlans.as_view(), name="public-plans"),
    path("events/", EventOptions.as_view(), name="event-options"),
    path("projects/",ProjectsList.as_view(),name="projects-list"),
    path("projects/<int:pk>/", ProjectDetail.as_view()),
    path("projects/<int:project_pk>/tasks/", ProjectTasks.as_view()),
    path("projects/<int:project_pk>/tasks/<int:pk>/", ProjectTaskDetail.as_view()),
    path("project-assignees/", ProjectAssigneeOptions.as_view()),
    path("catalog/plans/", catalog.PlanList.as_view(), name="catalog-plans"),
    path("catalog/plans/<int:pk>/", catalog.PlanDetail.as_view(), name="catalog-plan"),
    path("catalog/plans/<int:pk>/image/", catalog.PlanImage.as_view(), name="catalog-plan-image"),
    path("catalog/packages/", catalog.PackageList.as_view(), name="catalog-packages"),
    path("catalog/packages/<int:pk>/", catalog.PackageDetail.as_view(), name="catalog-package"),
    path("catalog/contents/", catalog.ContentList.as_view(), name="catalog-contents"),
    path("catalog/contents/<int:pk>/", catalog.ContentDetail.as_view(), name="catalog-content"),

]
