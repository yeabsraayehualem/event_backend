from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from event.models import Plan, Project
from event.serializers import ProjectDetailSerializer, ProjectListSerializer
from utils.formatter import Formatter
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView, RetrieveUpdateAPIView


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



class ProjectDetail(RetrieveAPIView):
    queryset = Project.objects.select_related("event", "lead").prefetch_related("tasks__assignees")
    serializer_class = ProjectDetailSerializer