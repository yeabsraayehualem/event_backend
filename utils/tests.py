from datetime import date

from rest_framework.test import APITestCase

from accounts.models import User
from crm.models import Customers, Lead
from event.models import Plan
from utils.rbac import MODULES, can, permissions_for


def make(role, phone):
    return User.objects.create_user(username=phone, phone=phone, password="Strong-pass-123", role=role)


class MatrixTests(APITestCase):
    def test_super_can_do_everything_and_admin_everything_listed(self):
        root, admin = make("super", "01"), make("admin", "02")
        for module, rules in MODULES.items():
            for action in rules:
                if action == "label":
                    continue
                self.assertTrue(can(root, module, action), (module, action))
                self.assertTrue(can(admin, module, action), (module, action))

    def test_segregation_of_duties(self):
        hr, finance, pm, sales = make("hr", "03"), make("finance", "04"), make("pm", "05"), make("sales", "06")
        self.assertTrue(can(hr, "payroll", "create"))
        self.assertFalse(can(hr, "payroll", "approve"))
        self.assertTrue(can(finance, "payroll", "approve"))
        self.assertTrue(can(pm, "purchase_orders", "create"))
        self.assertFalse(can(pm, "purchase_orders", "approve"))
        self.assertFalse(can(sales, "expenses"))
        self.assertFalse(can(make("staff", "07"), "dashboard"))

    def test_profile_sends_the_permissions(self):
        hr = make("hr", "08")
        self.client.force_authenticate(hr)
        permissions = self.client.get("/api/v1/user/profile/").json()["data"]["permissions"]
        self.assertEqual(permissions, permissions_for(hr))
        self.assertIn("payroll", permissions)
        self.assertNotIn("approve", permissions["payroll"])
        self.assertNotIn("expenses", permissions)


class EndpointTests(APITestCase):
    def setUp(self):
        plan = Plan.objects.create(name="Wedding")
        self.seller = make("sales", "10")
        other = make("sales", "11")
        for owner in (self.seller, other):
            Lead.objects.create(customer=Customers.objects.create(name=f"C{owner.pk}", phone=f"09{owner.pk}"), plan=plan,
                                plan_date=date(2027, 1, 1), location="Addis", assigned_sales_person=owner)

    def get(self, role, path):
        user = User.objects.filter(phone=f"2{role}").first() or make(role, f"2{role}")
        self.client.force_authenticate(user)
        return self.client.get(path)

    def test_admin_sees_every_lead_and_sales_only_their_own(self):
        self.assertEqual(len(self.get("admin", "/api/v1/crm/sales/leads/?status=all").json()), 2)
        self.client.force_authenticate(self.seller)
        self.assertEqual(len(self.client.get("/api/v1/crm/sales/leads/?status=all").json()), 1)

    def test_dashboard_sections_follow_the_role(self):
        finance = self.get("finance", "/api/v1/crm/sales/dashboard/").json()["data"]
        self.assertIsNone(finance["summary"])
        self.assertIsNotNone(finance["financials"])
        self.assertIsNotNone(finance["receivables"])

        pm = self.get("pm", "/api/v1/crm/sales/dashboard/").json()["data"]
        self.assertEqual((pm["summary"], pm["financials"], pm["receivables"]), (None, None, None))
        self.assertIsNotNone(pm["upcoming_events"])
        self.assertEqual(self.get("hr", "/api/v1/crm/sales/dashboard/").status_code, 403)

        self.client.force_authenticate(self.seller)
        sales = self.client.get("/api/v1/crm/sales/dashboard/").json()["data"]
        self.assertEqual((sales["scope"], sales["summary"]["total_leads"], sales["financials"]), ("assigned_to_me", 1, None))

        self.assertEqual(self.get("staff", "/api/v1/crm/sales/dashboard/").status_code, 403)

    def test_module_gates(self):
        cases = [
            ("sales", "/api/v1/finance/expenses/", 403), ("finance", "/api/v1/finance/expenses/", 200),
            ("pm", "/api/v1/hr/pay-runs/", 403), ("hr", "/api/v1/hr/pay-runs/", 200),
            ("stock", "/api/v1/procurement/vendors/", 200), ("stock", "/api/v1/hr/employees/", 403),
            ("admin", "/api/v1/finance/invoices/", 200), ("admin", "/api/v1/event/projects/", 200),
            ("hr", "/api/v1/user/users/", 403),
            ("sales", "/api/v1/finance/invoices/", 403), ("sales", "/api/v1/event/catalog/plans/", 403),
            ("sales", "/api/v1/event/events/", 403), ("sales", "/api/v1/crm/sales/lead-form-options/", 200),
        ]
        for role, path, expected in cases:
            with self.subTest(role=role, path=path):
                self.assertEqual(self.get(role, path).status_code, expected)
