from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from accounts.models import User
from event.models import Event, Plan, Project, Task
from event.serializers import ProjectDetailSerializer, ProjectListSerializer, ProjectStatusSerializer, TaskSerializer, UserSerializer
from utils.formatter import Formatter
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from utils.permissions import IsEventStaff, IsPM
from chatter.tracking import log_changes, post_message, snapshot

PROJECT_TRACKED_FIELDS = ["status"]
TASK_TRACKED_FIELDS = ["name", "status", "start_date", "end_date", "assignees"]
TASK_FIELD_LABELS = {"name": "Task name", "assignees": "Assignees"}


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


class EventOptions(APIView):
    """Events to pick from when creating a project or an invoice."""

    permission_classes = [IsEventStaff]

    def get(self, request):
        events = Event.objects.select_related("customer", "plan", "package").exclude(status=Event.Status.CANCELLED)
        return Response([
            {
                "id": event.id,
                "name": event.name,
                "customer": event.customer.name,
                "event_date": event.event_date.isoformat(),
                "plan": event.plan.name,
                "package": event.package.name if event.package_id else None,
                "status": event.status,
            }
            for event in events.order_by("-event_date", "-id")
        ])


class ProjectsList(ListCreateAPIView):

    queryset = Project.objects.all()
    serializer_class = ProjectListSerializer
    permission_classes = [IsPM]

    def perform_create(self, serializer):
        project = serializer.save()
        post_message(project, body="Project created.", author=self.request.user)



class ProjectDetail(RetrieveUpdateAPIView):
    queryset = Project.objects.select_related("event", "lead").prefetch_related("tasks__assignees")
    permission_classes = [IsPM]

    def get_serializer_class(self):
        return ProjectDetailSerializer if self.request.method == "GET" else ProjectStatusSerializer

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, PROJECT_TRACKED_FIELDS)
        project = serializer.save()
        log_changes(project, before, PROJECT_TRACKED_FIELDS, self.request.user)


class ProjectTasks(ListCreateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsPM]

    def get_queryset(self):
        return Task.objects.filter(project_id=self.kwargs["project_pk"]).prefetch_related("assignees").order_by("start_date", "id")

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.kwargs["project_pk"])
        task = serializer.save(project=project)
        post_message(project, body=f"Task “{task.name}” added.", author=self.request.user)


class ProjectTaskDetail(RetrieveUpdateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsPM]

    def get_queryset(self):
        return Task.objects.filter(project_id=self.kwargs["project_pk"]).prefetch_related("assignees")

    def perform_update(self, serializer):
        task = serializer.instance
        before = snapshot(task, TASK_TRACKED_FIELDS)
        task = serializer.save()
        # Tasks are edited inline on the project form, so their history lives on the project's chatter.
        log_changes(
            task, before, TASK_TRACKED_FIELDS, self.request.user,
            body=f"Task “{task.name}” updated.", record=task.project, labels=TASK_FIELD_LABELS,
        )


class ProjectAssigneeOptions(APIView):
    permission_classes = [IsPM]

    def get(self, request):
        users = User.objects.filter(is_active=True).order_by("first_name", "last_name", "id")
        return Response(UserSerializer(users, many=True).data)
