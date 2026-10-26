from django.urls import path

from .views import ProjectAssigneeOptions, ProjectDetail, ProjectTaskDetail, ProjectTasks, ProjectsList, PublicPlans

urlpatterns = [
    path("plans/", PublicPlans.as_view(), name="public-plans"),
    path("projects/",ProjectsList.as_view(),name="projects-list"),
    path("projects/<int:pk>/", ProjectDetail.as_view()),
    path("projects/<int:project_pk>/tasks/", ProjectTasks.as_view()),
    path("projects/<int:project_pk>/tasks/<int:pk>/", ProjectTaskDetail.as_view()),
    path("project-assignees/", ProjectAssigneeOptions.as_view()),

]
