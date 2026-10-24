from rest_framework import serializers

from accounts.models import User
from event.models import Project, Task


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name"]


class TaskSerializer(serializers.ModelSerializer):
    assignees = UserSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = ["id", "name", "assignees", "start_date", "end_date", "status"]


class ProjectListSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="event.name", read_only=True)
    lead_name = serializers.CharField(source="lead.first_name", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "event", "lead", "event_name", "lead_name",
                  "start_date", "end_date", "status"]


class ProjectDetailSerializer(ProjectListSerializer):
    lead = UserSerializer(read_only=True)          # full lead object instead of just the id
    tasks = TaskSerializer(source="task_set", many=True, read_only=True)
    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + ["tasks"]