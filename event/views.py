from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from accounts.models import User
from event.models import Plan, Project, Task
from event.serializers import ProjectDetailSerializer, ProjectListSerializer, ProjectStatusSerializer, TaskSerializer, UserSerializer
from utils.formatter import Formatter
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from utils.permissions import IsPM


class PublicPlans(APIView):
    """Read-only plan and package catalog for the public company profile."""

    permission_classes = [AllowAny]

    def get(self, request):
        plans = Plan.objects.prefetch_related("packages__contents").all()
        data = []
        for plan in plans:
            packages = [
                {
                    "id": package.id,
                    "name": package.name,
                    "description": package.description,
                    "price": str(package.price),
                    "contents": [
                        {"name": content.name, "description": content.description}
                        for content in package.contents.all()
                    ],
                }
                for package in plan.packages.all()
            ]
            data.append(
                {
                    "id": plan.id,
                    "name": plan.name,
                    "description": plan.description,
                    "image": request.build_absolute_uri(plan.image.url) if plan.image else None,
                    "packages": packages,
                }
            )
        return Response(Formatter.success(data=data))


class ProjectsList(ListCreateAPIView):

    queryset = Project.objects.all()
    serializer_class = ProjectListSerializer
    permission_classes = [IsPM]



class ProjectDetail(RetrieveUpdateAPIView):
    queryset = Project.objects.select_related("event", "lead").prefetch_related("tasks__assignees")
    permission_classes = [IsPM]

    def get_serializer_class(self):
        return ProjectDetailSerializer if self.request.method == "GET" else ProjectStatusSerializer


class ProjectTasks(ListCreateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsPM]

    def get_queryset(self):
        return Task.objects.filter(project_id=self.kwargs["project_pk"]).prefetch_related("assignees").order_by("start_date", "id")

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.kwargs["project_pk"])
        serializer.save(project=project)


class ProjectTaskDetail(RetrieveUpdateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsPM]

    def get_queryset(self):
        return Task.objects.filter(project_id=self.kwargs["project_pk"]).prefetch_related("assignees")


class ProjectAssigneeOptions(APIView):
    permission_classes = [IsPM]

    def get(self, request):
        users = User.objects.filter(is_active=True).order_by("first_name", "last_name", "id")
        return Response(UserSerializer(users, many=True).data)
