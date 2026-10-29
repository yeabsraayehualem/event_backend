from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.contenttypes.models import ContentType

from chatter.models import Message
from chatter.serializers import MessageSerializer, NoteSerializer
from chatter.tracking import post_message
from crm.models import Lead
from event.models import Event, Project
from finance.models import CustomerInvoice
from utils.permissions import (
    IsLeadAssigneeOrSuper,
    IsPM,
    IsSalesOrFinanceOrSuper,
    IsSalesOrSuper,
)

# Which records expose a chatter, and who may read or write it.
# Each entry reuses the permission classes that guard the record's own API.
CHATTER_MODELS = {
    "lead": (Lead, [IsSalesOrSuper, IsLeadAssigneeOrSuper]),
    "event": (Event, [IsSalesOrSuper]),
    "project": (Project, [IsPM]),
    "invoice": (CustomerInvoice, [IsSalesOrFinanceOrSuper]),
}


class RecordChatter(APIView):
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        entry = CHATTER_MODELS.get(kwargs["model"])
        if entry is None:
            raise NotFound("This record type has no chatter.")
        model, permission_classes = entry
        self.record = get_object_or_404(model, pk=kwargs["pk"])
        for permission in (cls() for cls in permission_classes):
            if not permission.has_permission(request, self):
                self.permission_denied(request, message=getattr(permission, "message", None))
            if not permission.has_object_permission(request, self, self.record):
                self.permission_denied(request, message=getattr(permission, "message", None))

    def get(self, request, model, pk):
        messages = (
            Message.objects.filter(
                content_type=ContentType.objects.get_for_model(self.record),
                object_id=self.record.pk,
            )
            .select_related("author")
            .prefetch_related("tracking_values")
        )
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, model, pk):
        serializer = NoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = post_message(
            self.record,
            body=serializer.validated_data["body"],
            author=request.user,
            kind=Message.Kind.NOTE,
        )
        return Response(MessageSerializer(message).data, status=201)
