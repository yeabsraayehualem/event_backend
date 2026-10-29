from datetime import date

from rest_framework.test import APITestCase

from accounts.models import User
from crm.models import Customers, Lead
from event.models import Event, Package, Plan, Project, Task


class ChatterTrackingTests(APITestCase):
    def setUp(self):
        self.super_user = User.objects.create_user(
            username="admin", phone="0900000001", password="pass", role=User.Role.SUPER,
            first_name="Abebe", last_name="Kebede",
        )
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES)
        self.other_sales = User.objects.create_user(username="sales2", phone="0900000003", password="pass", role=User.Role.SALES)
        self.plan = Plan.objects.create(name="Wedding", image="plans/x.jpg", description="")
        self.package = Package.objects.create(plan=self.plan, name="Gold", price=100)
        customer = Customers.objects.create(name="Selam", phone="0911")
        self.lead = Lead.objects.create(
            customer=customer, plan=self.plan, plan_date=date(2026, 12, 1), location="Addis",
            assigned_sales_person=self.sales,
        )

    def chatter(self, model, pk):
        return self.client.get(f"/api/v1/chatter/{model}/{pk}/")

    def test_lead_update_logs_who_changed_what(self):
        self.client.force_authenticate(self.super_user)
        response = self.client.patch(
            f"/api/v1/crm/sales/leads/{self.lead.id}/",
            {"status": "contacted", "package_id": self.package.id, "location": "Addis"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        messages = self.chatter("lead", self.lead.id).json()
        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertEqual(message["kind"], "tracking")
        self.assertEqual(message["author"]["name"], "Abebe Kebede")
        changes = {value["field"]: (value["old_value"], value["new_value"]) for value in message["tracking_values"]}
        self.assertEqual(changes, {"status": ("Lead", "Contacted"), "package": ("", "Gold")})

    def test_saving_without_changes_logs_nothing(self):
        self.client.force_authenticate(self.super_user)
        self.client.patch(f"/api/v1/crm/sales/leads/{self.lead.id}/", {"location": "Addis"}, format="json")
        self.assertEqual(self.chatter("lead", self.lead.id).json(), [])

    def test_log_note_and_access_rules(self):
        self.client.force_authenticate(self.sales)
        response = self.client.post(f"/api/v1/chatter/lead/{self.lead.id}/", {"body": "Called the family."}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["kind"], "note")

        self.client.force_authenticate(self.other_sales)
        self.assertEqual(self.chatter("lead", self.lead.id).status_code, 403)
        self.assertEqual(self.chatter("unknown", 1).status_code, 404)

    def test_task_changes_are_logged_on_the_project(self):
        self.lead.status = Lead.Status.WON
        self.lead.save()
        event = Event.objects.create(
            lead=self.lead, customer=self.lead.customer, plan=self.plan,
            name="Selam wedding", event_date=date(2026, 12, 1), location="Addis",
        )
        project = Project.objects.create(name="Wedding prep", end_date=date(2026, 12, 1), event=event, lead=self.super_user)
        task = Task.objects.create(project=project, name="Book venue", start_date=date(2026, 11, 1), end_date=date(2026, 11, 2))

        self.client.force_authenticate(self.super_user)
        response = self.client.patch(
            f"/api/v1/event/projects/{project.id}/tasks/{task.id}/",
            {"status": "ongoing", "assignee_ids": [self.sales.id]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        message = self.chatter("project", project.id).json()[0]
        self.assertIn("Book venue", message["body"])
        fields = {value["field"]: value["new_value"] for value in message["tracking_values"]}
        self.assertEqual(fields, {"status": "On Going", "assignees": "0900000002"})

    def test_invoice_line_edits_are_logged(self):
        from event.models import Content
        from finance.models import CustomerInvoice, InvoiceLines

        self.lead.status = Lead.Status.WON
        self.lead.save()
        event = Event.objects.create(
            lead=self.lead, customer=self.lead.customer, plan=self.plan,
            name="Selam wedding", event_date=date(2026, 12, 1), location="Addis",
        )
        content = Content.objects.create(name="Catering")
        invoice = CustomerInvoice.objects.create(event=event, customer=event.customer, plan=self.plan)
        InvoiceLines.objects.create(invoice=invoice, content=content, inclusive_price=100)

        self.client.force_authenticate(self.super_user)
        response = self.client.patch(
            f"/api/v1/finance/invoices/{invoice.id}/",
            {"status": "paid", "lines": [{"content_id": content.id, "inclusive_price": "250.00"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], "250.00")
        message = self.chatter("invoice", invoice.id).json()[0]
        self.assertEqual(message["body"], "Invoice lines updated.")
        fields = {value["field"]: (value["old_value"], value["new_value"]) for value in message["tracking_values"]}
        self.assertEqual(fields, {"status": ("Unpaid", "Paid"), "total": ("100.00", "250.00")})


class ManualCreateTests(APITestCase):
    def setUp(self):
        self.super_user = User.objects.create_user(username="admin", phone="0900000001", password="pass", role=User.Role.SUPER)
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES)
        self.plan = Plan.objects.create(name="Wedding", image="plans/x.jpg", description="")
        self.package = Package.objects.create(plan=self.plan, name="Gold", price=100)
        customer = Customers.objects.create(name="Selam", phone="0911")
        lead = Lead.objects.create(customer=customer, plan=self.plan, plan_date=date(2026, 12, 1), location="Addis", status=Lead.Status.WON)
        self.event = Event.objects.create(
            lead=lead, customer=customer, plan=self.plan, package=self.package,
            name="Selam wedding", event_date=date(2026, 12, 1), location="Addis",
        )

    def test_sales_creates_lead_assigned_to_themselves(self):
        self.client.force_authenticate(self.sales)
        options = self.client.get("/api/v1/crm/sales/lead-form-options/").json()
        self.assertEqual(options["plans"][0]["packages"], [{"id": self.package.id, "name": "Gold"}])
        self.assertFalse(options["can_assign_sales"])
        response = self.client.post("/api/v1/crm/sales/leads/", {
            "customer_name": "Hana", "phone": "0922", "plan": self.plan.id,
            "package_id": self.package.id, "plan_date": "2027-01-10",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        lead = Lead.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual(lead.assigned_sales_person, self.sales)
        self.assertEqual(self.client.get(f"/api/v1/chatter/lead/{lead.id}/").json()[0]["body"], "Lead created.")

    def test_create_invoice_with_lines(self):
        from event.models import Content
        content = Content.objects.create(name="Catering")
        self.client.force_authenticate(self.super_user)
        self.assertEqual(self.client.get("/api/v1/event/events/").json()[0]["id"], self.event.id)
        response = self.client.post("/api/v1/finance/invoices/", {
            "event_id": self.event.id, "milestone_name": "Deposit",
            "lines": [{"content_id": content.id, "inclusive_price": "500.00"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        body = response.json()
        self.assertEqual((body["customer_name"], body["total"]), ("Selam", "500.00"))

    def test_create_project_validates_dates(self):
        self.client.force_authenticate(self.super_user)
        payload = {"name": "Prep", "event": self.event.id, "lead": self.super_user.id, "start_date": "2026-11-10", "end_date": "2026-11-01"}
        self.assertEqual(self.client.post("/api/v1/event/projects/", payload, format="json").status_code, 400)
        payload["end_date"] = "2026-11-30"
        response = self.client.post("/api/v1/event/projects/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Project.objects.get().name, "Prep")
