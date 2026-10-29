from datetime import date, timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from crm.automation import split_amount
from crm.models import Customers, Lead
from event.models import Content, Event, EventType, Package, Plan, Project
from finance.models import CustomerInvoice


class WonLeadAutomationTests(APITestCase):
    def setUp(self):
        self.super_user = User.objects.create_user(username="admin", phone="0900000001", password="pass", role=User.Role.SUPER)
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES, first_name="Saba")
        plan = Plan.objects.create(name="Wedding", image="plans/x.jpg", description="")
        self.package = Package.objects.create(plan=plan, name="Gold", price=Decimal("600000.00"))
        self.package.contents.set([Content.objects.create(name="Catering"), Content.objects.create(name="Decor")])
        wedding = EventType.objects.create(plan=plan, name="Wedding")
        self.lead = Lead.objects.create(
            customer=Customers.objects.create(name="Selam", phone="0911"), plan=plan, package=self.package,
            plan_date=date(2027, 3, 1), location="Addis", event_type=wedding,
            status=Lead.Status.NEGOTIATION, assigned_sales_person=self.sales,
        )

    def win(self, user=None):
        self.client.force_authenticate(user or self.sales)
        return self.client.patch(f"/api/v1/crm/sales/leads/{self.lead.id}/", {"status": "won"}, format="json")

    def test_winning_creates_event_deposit_invoice_and_project(self):
        response = self.win()
        self.assertEqual(response.status_code, 200)
        body = response.json()

        event = Event.objects.get(lead=self.lead)
        invoice = CustomerInvoice.objects.get(event=event)
        project = Project.objects.get(event=event)
        self.assertEqual((body["event_id"], body["invoice_ids"], body["project_ids"]), (event.id, [invoice.id], [project.id]))

        self.assertEqual(invoice.milestone_name, "Deposit")
        self.assertEqual(invoice.total, Decimal("180000.00"))  # 30% of 600,000
        self.assertEqual(sorted(invoice.lines.values_list("inclusive_price", flat=True)), [Decimal("90000.00")] * 2)
        self.assertEqual(invoice.due_date, timezone.localdate() + timedelta(days=7))

        self.assertEqual(project.lead, self.sales)
        self.assertEqual((project.end_date, project.status), (date(2027, 3, 1), "draft"))

        summary = self.client.get(f"/api/v1/chatter/lead/{self.lead.id}/").json()[0]["body"]
        self.assertIn(invoice.reference, summary)
        self.assertIn("ETB 180,000.00", summary)
        invoice_note = self.client.get(f"/api/v1/chatter/invoice/{invoice.id}/").json()[0]["body"]
        self.assertIn("Deposit of 30% of the package price", invoice_note)
        self.assertIn("preparation", summary)

    def test_winning_again_does_not_duplicate(self):
        self.win()
        self.client.patch(f"/api/v1/crm/sales/leads/{self.lead.id}/", {"status": "negotiation"}, format="json")
        self.win()
        self.assertEqual(
            (Event.objects.count(), CustomerInvoice.objects.count(), Project.objects.count()), (1, 1, 1),
        )

    def test_lead_without_package_gets_project_but_no_invoice(self):
        self.lead.package = None
        self.lead.assigned_sales_person = None
        self.lead.save()
        self.win(self.super_user)
        self.assertFalse(CustomerInvoice.objects.exists())
        self.assertEqual(Project.objects.get().lead, self.super_user)  # unassigned: whoever won it
        messages = [m["body"] for m in self.client.get(f"/api/v1/chatter/lead/{self.lead.id}/").json()]
        self.assertTrue(any("No package was chosen" in body for body in messages))

    @override_settings(LEAD_WON_DEPOSIT_PERCENT="50")
    def test_deposit_percent_is_configurable(self):
        self.win()
        self.assertEqual(CustomerInvoice.objects.get().total, Decimal("300000.00"))

    def test_convert_backfills_leads_won_before_automation(self):
        Lead.objects.filter(pk=self.lead.pk).update(status=Lead.Status.WON)  # won without the automation
        self.client.force_authenticate(self.sales)
        response = self.client.post(f"/api/v1/crm/sales/leads/{self.lead.id}/convert/")
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertIsNotNone(data["invoice_id"])
        self.assertIsNotNone(data["project_id"])

    def test_split_amount_keeps_every_cent(self):
        self.assertEqual(split_amount(Decimal("10.00"), 3), [Decimal("3.33"), Decimal("3.33"), Decimal("3.34")])


class DashboardTests(APITestCase):
    def setUp(self):
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES)
        self.other = User.objects.create_user(username="sales2", phone="0900000003", password="pass", role=User.Role.SALES)
        plan = Plan.objects.create(name="Wedding", image="plans/x.jpg", description="")
        package = Package.objects.create(plan=plan, name="Gold", price=Decimal("1000.00"))
        package.contents.set([Content.objects.create(name="Catering")])
        self.event_date = timezone.localdate() + timedelta(days=20)
        for owner in (self.sales, self.other):
            lead = Lead.objects.create(
                customer=Customers.objects.create(name=f"C{owner.id}", phone=f"09{owner.id}"), plan=plan, package=package,
                plan_date=self.event_date, location="Addis", status=Lead.Status.NEGOTIATION, assigned_sales_person=owner,
            )
            self.client.force_authenticate(owner)
            self.client.patch(f"/api/v1/crm/sales/leads/{lead.id}/", {"status": "won"}, format="json")
        CustomerInvoice.objects.filter(event__lead__assigned_sales_person=self.sales).update(
            due_date=timezone.localdate() - timedelta(days=1),
        )

    def test_dashboard_is_scoped_to_the_sales_person(self):
        self.client.force_authenticate(self.sales)
        data = self.client.get("/api/v1/crm/sales/dashboard/").json()["data"]

        self.assertEqual(len(data["monthly_inquiries"]), 6)
        this_month = data["monthly_inquiries"][-1]
        self.assertEqual((this_month["inquiries"], this_month["won"]), (1, 1))

        receivables = data["receivables"]
        self.assertEqual((receivables["outstanding_count"], receivables["outstanding_total"]), (1, "300.00"))
        self.assertEqual((receivables["overdue_count"], receivables["overdue_total"]), (1, "300.00"))

        [event] = data["upcoming_events"]
        self.assertEqual((event["days_away"], event["unpaid_count"], event["tasks_total"]), (20, 1, 0))
        self.assertIsNotNone(event["project_id"])
