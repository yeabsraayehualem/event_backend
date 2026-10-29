from rest_framework import serializers

from chatter.models import Message, TrackingValue


class TrackingValueSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackingValue
        fields = ["field", "field_label", "old_value", "new_value"]


class MessageSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    tracking_values = TrackingValueSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = ["id", "kind", "body", "author", "created_at", "tracking_values"]

    def get_author(self, message):
        if message.author is None:
            return None
        return {
            "id": message.author.id,
            "name": message.author.get_full_name() or message.author.phone,
        }


class NoteSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000, trim_whitespace=True)
