from rest_framework import serializers

from accounts.models import User
from event.models import Project, Task


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name"]


class TaskSerializer(serializers.ModelSerializer):
    assignees = UserSerializer(many=True, read_only=True)
    assignee_ids = serializers.PrimaryKeyRelatedField(
        source="assignees",
        queryset=User.objects.filter(is_active=True),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = Task
        fields = ["id", "name", "assignees", "assignee_ids", "start_date", "end_date", "status"]
        read_only_fields = ["id"]


class ProjectListSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="event.name", read_only=True)
    lead_name = serializers.CharField(source="lead.first_name", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "event", "lead", "event_name", "lead_name",
                  "start_date", "end_date", "status"]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "The end date must be on or after the start date."})
        return attrs


class ProjectDetailSerializer(ProjectListSerializer):
    lead = UserSerializer(read_only=True)          # full lead object instead of just the id
    tasks = TaskSerializer(source="task_set", many=True, read_only=True)
    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + ["tasks"]


class ProjectStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "status"]
        read_only_fields = ["id"]
