from rest_framework import serializers

from utils.rbac import permissions_for

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """The signed-in user, with what their role may do (`{module: [actions]}`) for the frontend."""

    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "phone", "first_name", "last_name", "email", "role", "permissions"]

    def get_permissions(self, user):
        return permissions_for(user)
