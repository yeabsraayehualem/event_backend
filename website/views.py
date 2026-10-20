from django.shortcuts import render
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from event.models import Package, Plan
from crm.models import Customers,Lead
from . import serializers
# Create your views here.
from .serializers import GetPlans
from rest_framework.generics import ListAPIView
from django.db import transaction
from django.conf import settings
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.response import Response
from .models import ShowcaseEntry
from utils.formatter import Formatter

class PlanListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = GetPlans
    queryset = Plan.objects.prefetch_related("packages__contents")


class PublicShowcaseView(ListAPIView):
    serializer_class = serializers.ShowcaseSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = ShowcaseEntry.objects.filter(published=True)
        kind = self.request.query_params.get("kind")
        if kind in ShowcaseEntry.Kind.values:
            queryset = queryset.filter(kind=kind)
        return queryset

class PublicLeadCreate(APIView):
    """Accept a client inquiry and add it to the CRM lead pipeline."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = serializers.PublicLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        with transaction.atomic():
            customer, created = Customers.objects.get_or_create(
                phone=values["phone"],
                defaults={"name": values["name"], "email": values.get("email") or None},
            )
            if not created and values.get("email") and not customer.email:
                customer.email = values["email"]
                customer.save(update_fields=["email"])
            lead = Lead.objects.create(
                customer=customer,
                plan=values["plan"],
                package=values.get("package"),
                plan_date=values["plan_date"],
                location=values["location"],
                notes=values.get("notes", ""),
                event_type=values.get("event_type", ""),
                guest_count=values.get("guest_count"),
                budget_tier=values.get("budget_tier", ""),
                requirements=values.get("requirements", ""),
            )
        if values.get("email") or customer.email:
            send_mail(
                subject="We received your celebration inquiry",
                message=(
                    f"Hello {customer.name},\n\nThank you for contacting Bahran Events. "
                    "Our team has received your inquiry and will be in touch to discuss your celebration.\n\n"
                    "With warm regards,\nBahran Events"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[values.get("email") or customer.email],
                fail_silently=True,
            )
        return Response(
            Formatter.success(data={"lead_id": lead.id}, message="Inquiry received"),
            status=status.HTTP_201_CREATED,
        )
