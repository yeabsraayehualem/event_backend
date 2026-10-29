from datetime import date
from decimal import Decimal

from rest_framework.test import APITestCase

from accounts.models import User
from crm.models import Customers, Lead
from event.models import Content, EventType, Package, Plan


class CatalogTests(APITestCase):
    def setUp(self):
        self.super_user = User.objects.create_user(username="admin", phone="0900000001", password="pass", role=User.Role.SUPER)
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES)

    def test_sales_can_read_but_not_change_the_catalog(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(self.client.get("/api/v1/event/catalog/plans/").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/event/catalog/plans/", {"name": "Wedding"}, format="json").status_code, 403)

    def test_plan_event_types_are_created_renamed_and_protected(self):
        self.client.force_authenticate(self.super_user)
        response = self.client.post("/api/v1/event/catalog/plans/", {
            "name": "Wedding", "event_types": [{"name": "Teklil"}, {"name": "Civil"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        plan_id = response.json()["id"]
        teklil, civil = EventType.objects.filter(plan_id=plan_id).order_by("sequence")
        Lead.objects.create(
            customer=Customers.objects.create(name="Selam", phone="0911"), plan_id=plan_id,
            plan_date=date(2027, 1, 1), location="Addis", event_type=teklil,
        )

        # Rename the used one, drop the unused one, add a new one.
        response = self.client.patch(f"/api/v1/event/catalog/plans/{plan_id}/", {
            "event_types": [{"id": teklil.id, "name": "Church wedding (Teklil)"}, {"name": "Melse"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual([item["name"] for item in response.json()["event_types"]], ["Church wedding (Teklil)", "Melse"])
        self.assertFalse(EventType.objects.filter(pk=civil.pk).exists())
        log = self.client.get(f"/api/v1/chatter/plan/{plan_id}/").json()[0]["body"]
        self.assertIn("renamed “Teklil” to “Church wedding (Teklil)”", log)
        self.assertIn("removed “Civil”", log)

        # An event type a lead uses can't be removed.
        response = self.client.patch(f"/api/v1/event/catalog/plans/{plan_id}/", {"event_types": []}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("used by 1 lead", str(response.json()))

    def test_package_price_change_is_tracked(self):
        self.client.force_authenticate(self.super_user)
        plan = Plan.objects.create(name="Wedding")
        catering = Content.objects.create(name="Catering")
        response = self.client.post("/api/v1/event/catalog/packages/", {
            "plan": plan.id, "name": "Gold", "price": "1000.00", "content_ids": [catering.id],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        package_id = response.json()["id"]
        self.client.patch(f"/api/v1/event/catalog/packages/{package_id}/", {"price": "1200.00"}, format="json")
        change = self.client.get(f"/api/v1/chatter/package/{package_id}/").json()[0]["tracking_values"][0]
        self.assertEqual((change["field"], change["old_value"], change["new_value"]), ("price", "1000.00", "1200.00"))


class LeadEventTypeTests(APITestCase):
    def setUp(self):
        self.sales = User.objects.create_user(username="sales", phone="0900000002", password="pass", role=User.Role.SALES)
        self.wedding = Plan.objects.create(name="Wedding")
        self.christening = Plan.objects.create(name="Kiristina")
        self.teklil = EventType.objects.create(plan=self.wedding, name="Teklil")
        self.kiristina = EventType.objects.create(plan=self.christening, name="Kiristina")

    def test_event_type_must_belong_to_the_plan(self):
        self.client.force_authenticate(self.sales)
        payload = {"customer_name": "Hana", "phone": "0922", "plan": self.wedding.id, "plan_date": "2027-01-10"}
        bad = self.client.post("/api/v1/crm/sales/leads/", {**payload, "event_type_id": self.kiristina.id}, format="json")
        self.assertEqual(bad.status_code, 400)
        good = self.client.post("/api/v1/crm/sales/leads/", {**payload, "event_type_id": self.teklil.id}, format="json")
        self.assertEqual(good.status_code, 201)
        self.assertEqual(good.json()["data"]["event_type"], "Teklil")

    def test_website_inquiry_validates_and_lists_event_types(self):
        plans = self.client.get("/api/v1/website/plans/").json()
        wedding = next(plan for plan in plans if plan["id"] == self.wedding.id)
        self.assertEqual(wedding["event_types"], [{"id": self.teklil.id, "name": "Teklil"}])
        payload = {"name": "Hana", "phone": "0922", "email": "h@example.com", "plan": self.wedding.id,
                   "plan_date": "2027-01-10", "location": "Addis"}
        self.assertEqual(self.client.post("/api/v1/website/public/leads/", {**payload, "event_type": self.kiristina.id}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/v1/website/public/leads/", {**payload, "event_type": self.teklil.id}, format="json").status_code, 201)
        self.assertEqual(Lead.objects.get().event_type, self.teklil)
