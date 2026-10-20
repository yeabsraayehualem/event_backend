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
from rest_framework import status
from rest_framework.response import Response
from utils.formatter import Formatter

class PlanListView(ListAPIView):
    serializer_class = GetPlans
    queryset = Plan.objects.prefetch_related("packages__contents")

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
            )
        return Response(
            Formatter.success(data={"lead_id": lead.id}, message="Inquiry received"),
            status=status.HTTP_201_CREATED,
        )
