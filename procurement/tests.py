from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import User
from crm.models import Customers, Lead
from event.models import Event, Plan
from finance.models import TaxRate
from procurement.models import PurchaseOrder, Vendor, VendorCategory

BASE = "/api/v1/procurement"


def make_user(role, phone):
    return User.objects.create_user(username=f"{role}{phone}", phone=phone, password="pass", role=role)


class ProcurementTestCase(APITestCase):
    def setUp(self):
        self.pm = make_user(User.Role.PM, "0900000001")
        self.finance = make_user(User.Role.FINANCE, "0900000002")
        self.sales = make_user(User.Role.SALES, "0900000003")
        customer = Customers.objects.create(name="Selam", phone="0911")
        plan = Plan.objects.create(name="Wedding")
        lead = Lead.objects.create(customer=customer, plan=plan, plan_date=date(2027, 1, 10), location="Addis")
        self.event = Event.objects.create(
            lead=lead, customer=customer, plan=plan, name="Selam — Wedding", event_date=date(2027, 1, 10), location="Addis",
        )
        self.catering = VendorCategory.objects.get(name="Catering")
        self.vendor = Vendor.objects.create(name="Yod Abyssinia Catering", category=self.catering, phone="0922")
        self.vat = TaxRate.objects.create(name="VAT 15% (excl.)", kind=TaxRate.Kind.VAT, rate=Decimal("15"), inclusive=False)
        self.wht = TaxRate.objects.create(name="Withholding 3%", kind=TaxRate.Kind.WITHHOLDING, rate=Decimal("3"), inclusive=False)

    def order_payload(self, **overrides):
        payload = {
            "vendor": self.vendor.id,
            "event": self.event.id,
            "delivery_location": "Venue kitchen",
            "lines": [
                {"kind": "service", "description": "Buffet dinner", "quantity": "200", "unit_price": "450.00", "tax_profile_ids": [self.vat.id, self.wht.id]},
                {"kind": "rental", "description": "Chafing dishes", "quantity": "10", "unit_price": "100.00"},
            ],
        }
        payload.update(overrides)
        return payload

    def create_order(self, **overrides):
        self.client.force_authenticate(self.pm)
        response = self.client.post(f"{BASE}/purchase-orders/", self.order_payload(**overrides), format="json")
        self.assertEqual(response.status_code, 201, response.json())
        return response.json()

    def transition(self, order_id, action, user, **extra):
        self.client.force_authenticate(user)
        return self.client.post(f"{BASE}/purchase-orders/{order_id}/transition/", {"action": action, **extra}, format="json")


class AccessTests(ProcurementTestCase):
    def test_sales_cannot_reach_procurement(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(self.client.get(f"{BASE}/vendors/").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/purchase-orders/").status_code, 403)

    def test_default_categories_are_seeded(self):
        self.client.force_authenticate(self.pm)
        names = [item["name"] for item in self.client.get(f"{BASE}/categories/").json()]
        self.assertIn("Catering", names)
        self.assertIn("Photography & video", names)
        self.assertIn("Equipment & material rental", names)


class VendorTests(ProcurementTestCase):
    def test_vendor_changes_are_tracked(self):
        self.client.force_authenticate(self.pm)
        response = self.client.post(f"{BASE}/vendors/", {
            "name": "Lens Studio", "category": VendorCategory.objects.get(name="Photography & video").id,
            "phone": "0933", "payment_terms": "net_15",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        vendor_id = response.json()["id"]
        self.client.patch(f"{BASE}/vendors/{vendor_id}/", {"payment_terms": "advance"}, format="json")
        change = self.client.get(f"/api/v1/chatter/vendor/{vendor_id}/").json()[0]["tracking_values"][0]
        self.assertEqual((change["old_value"], change["new_value"]), ("15 days after delivery", "Full payment in advance"))

    @override_settings(MEDIA_ROOT="/tmp/event-org-test-media")
    def test_compliance_document_upload(self):
        self.client.force_authenticate(self.pm)
        upload = SimpleUploadedFile("license.pdf", b"%PDF-1.4", content_type="application/pdf")
        response = self.client.post(
            f"{BASE}/vendors/{self.vendor.id}/documents/",
            {"kind": "business_license", "file": upload, "expires_on": "2020-01-01"},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.json())
        document = self.client.get(f"{BASE}/vendors/{self.vendor.id}/").json()["documents"][0]
        self.assertEqual(document["kind_label"], "Business license")
        self.assertTrue(document["is_expired"])

    def test_vendor_shows_engagement_history(self):
        order = self.create_order()
        vendor = self.client.get(f"{BASE}/vendors/{self.vendor.id}/").json()
        self.assertEqual([item["reference"] for item in vendor["purchase_orders"]], [order["reference"]])


class PurchaseOrderTests(ProcurementTestCase):
    def test_totals_reference_and_taxes(self):
        order = self.create_order()
        self.assertRegex(order["reference"], r"^PO-\d{4}-0001$")
        buffet, dishes = order["lines"]
        # 200 × 450 = 90,000; +15% VAT 13,500; −3% withholding 2,700.
        self.assertEqual((buffet["subtotal"], buffet["tax"], buffet["total"]), ("90000.00", "10800.00", "100800.00"))
        self.assertEqual(dishes["total"], "1000.00")
        self.assertEqual((order["subtotal"], order["tax"], order["total"]), ("91000.00", "10800.00", "101800.00"))
        self.assertEqual(order["status"], "draft")

    def test_needs_lines_and_matching_payment_schedule(self):
        self.client.force_authenticate(self.pm)
        response = self.client.post(f"{BASE}/purchase-orders/", self.order_payload(lines=[]), format="json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(f"{BASE}/purchase-orders/", self.order_payload(payment_schedule=[
            {"label": "Deposit", "amount": "50000.00"},
        ]), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("adds up to 50,000.00", str(response.json()))
        self.assertFalse(PurchaseOrder.objects.exists())
        self.create_order(payment_schedule=[
            {"label": "Deposit", "amount": "50000.00", "due_date": "2026-12-01"},
            {"label": "Balance on delivery", "amount": "51800.00"},
        ])

    def test_cancelled_event_and_inactive_vendor_are_rejected(self):
        self.client.force_authenticate(self.pm)
        self.vendor.active = False
        self.vendor.save()
        self.assertEqual(self.client.post(f"{BASE}/purchase-orders/", self.order_payload(), format="json").status_code, 400)
        self.vendor.active = True
        self.vendor.save()
        self.event.status = Event.Status.CANCELLED
        self.event.save()
        self.assertEqual(self.client.post(f"{BASE}/purchase-orders/", self.order_payload(), format="json").status_code, 400)

    def test_workflow_and_edit_lock(self):
        order = self.create_order()
        self.assertEqual(self.transition(order["id"], "submit", self.pm).status_code, 200)

        # Submitted orders are locked.
        self.client.force_authenticate(self.pm)
        response = self.client.patch(f"{BASE}/purchase-orders/{order['id']}/", {"notes": "x"}, format="json")
        self.assertEqual(response.status_code, 400)

        # Event managers can't approve their own spend.
        self.assertEqual(self.transition(order["id"], "approve", self.pm).status_code, 403)
        response = self.transition(order["id"], "approve", self.finance)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["status"], "approved")
        self.assertIsNotNone(response.json()["approved_by_name"])

        self.assertEqual(self.transition(order["id"], "receive", self.pm).json()["status"], "received")
        self.assertEqual(self.transition(order["id"], "cancel", self.finance, reason="x").status_code, 400)

        history = self.client.get(f"/api/v1/chatter/purchaseorder/{order['id']}/").json()
        self.assertEqual(
            [message["tracking_values"][0]["new_value"] for message in history if message["tracking_values"]],
            ["Received", "Approved", "Waiting approval"],
        )

    def test_reject_and_cancel_need_a_reason(self):
        order = self.create_order()
        self.transition(order["id"], "submit", self.pm)
        self.assertEqual(self.transition(order["id"], "reject", self.finance).status_code, 400)
        response = self.transition(order["id"], "reject", self.finance, reason="Get a second quote")
        self.assertEqual(response.json()["status"], "draft")
        self.assertEqual(self.transition(order["id"], "cancel", self.pm, reason="Customer dropped catering").json()["status"], "cancelled")

    def test_only_approvers_cancel_an_approved_order(self):
        order = self.create_order()
        self.transition(order["id"], "submit", self.pm)
        self.transition(order["id"], "approve", self.finance)
        self.assertEqual(self.transition(order["id"], "cancel", self.pm, reason="no").status_code, 403)
        self.assertEqual(self.transition(order["id"], "cancel", self.finance, reason="Vendor closed").status_code, 200)


class BudgetTests(ProcurementTestCase):
    def test_budget_commitment_and_overrun_confirmation(self):
        self.client.force_authenticate(self.pm)
        response = self.client.patch(f"{BASE}/events/{self.event.id}/", {"cost_budget": "100000"}, format="json")
        self.assertEqual(response.status_code, 200, response.json())

        order = self.create_order()
        self.transition(order["id"], "submit", self.pm)
        summary = self.client.get(f"{BASE}/events/{self.event.id}/").json()
        self.assertEqual((summary["committed"], summary["pending"]), ("0.00", "101800.00"))

        response = self.transition(order["id"], "approve", self.finance)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["over_budget"], "1800.00")

        response = self.transition(order["id"], "approve", self.finance, confirm_over_budget=True)
        self.assertEqual(response.status_code, 200)
        budget = response.json()["budget"]
        self.assertEqual((budget["committed"], budget["remaining"]), ("101800.00", "-1800.00"))

    def test_sales_cannot_set_budget(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(self.client.patch(f"{BASE}/events/{self.event.id}/", {"cost_budget": "1"}, format="json").status_code, 403)

