from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from . import serializers
from crm.models import Lead
from crm.models import Customers
from utils.formatter import Formatter
from utils.views import SalesView
from rest_framework.response import Response




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


class SalesDashboard(SalesView):


    def get(self, request,*a, **kw):
        leads = Lead.objects.all().count()
        open_leads = Lead.objects.filter(status="lead").count()
        assigned = Lead.objects.filter(assigned_sales_person= request.user,status="lead").count()
        won = Lead.objects.filter(status="won").count()
        sales_won = Lead.objects.filter(status="won",assigned_sales_person = request.user).count()
        lost = Lead.objects.filter(status="lost").count()
        sales_lost = Lead.objects.filter(status="lost",assigned_sales_person = request.user).count()


        data = {
            "total_leads":leads,
            "open_leads":open_leads,
            "assigned":assigned,
            "won":won,
            "my_win":sales_won,
            "lost":lost,
            "my_loss":sales_lost
        }


        data = Formatter.success(data=data)

        return Response(data)


