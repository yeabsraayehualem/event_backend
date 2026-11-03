from datetime import date
from decimal import Decimal

from accounts.models import User
from event.models import Content
from finance.models import CustomerInvoice, ExpenseCategory, InvoiceLines
from procurement.tests import ProcurementTestCase, make_user


class ExpenseTestCase(ProcurementTestCase):
    def setUp(self):
        super().setUp()
        self.boss = make_user(User.Role.SUPER, "0900000009")
        self.fuel = ExpenseCategory.objects.get(name="Transport & fuel")
        self.vendor_services = ExpenseCategory.objects.get(name="Vendor services")

    def approved_order(self, **overrides):
        order = self.create_order(**overrides)
        self.transition(order["id"], "submit", self.pm)
        return self.transition(order["id"], "approve", self.finance).json()

    def record(self, user=None, **payload):
        self.client.force_authenticate(user or self.finance)
        return self.client.post("/api/v1/finance/expenses/", payload, format="json")


class ExpenseTests(ExpenseTestCase):
    def test_only_finance_records_expenses(self):
        payload = {"category": self.fuel.id, "description": "Fuel for van", "amount": "1500.00"}
        self.assertEqual(self.record(self.pm, **payload).status_code, 403)
        response = self.record(**payload)
        self.assertEqual(response.status_code, 201, response.json())
        body = response.json()
        self.assertRegex(body["reference"], r"^EXP-\d{4}-0001$")
        self.assertEqual((body["total"], body["event"], body["source"]), ("1500.00", None, "manual"))

    def test_vendor_bill_takes_event_and_vendor_from_the_order(self):
        order = self.approved_order(payment_schedule=[
            {"label": "Deposit", "amount": "50000.00"}, {"label": "Balance", "amount": "51800.00"},
        ])
        deposit = order["payment_schedule"][0]
        response = self.record(
            category=self.vendor_services.id, description="Catering deposit", purchase_order=order["id"],
            scheduled_payment=deposit["id"], amount="44695.68", tax="5304.32",
        )
        self.assertEqual(response.status_code, 201, response.json())
        bill = response.json()
        self.assertEqual((bill["event"], bill["vendor"], bill["source"]), (self.event.id, self.vendor.id, "purchase_order"))

        # The same milestone can't be paid twice, and bills can't exceed the order.
        again = self.record(category=self.vendor_services.id, description="x", purchase_order=order["id"], scheduled_payment=deposit["id"], amount="1")
        self.assertIn("already paid", str(again.json()))
        too_much = self.record(category=self.vendor_services.id, description="x", purchase_order=order["id"], amount="60000")
        self.assertIn("Only 51,800.00 is left", str(too_much.json()))

        detail = self.client.get(f"/api/v1/procurement/purchase-orders/{order['id']}/").json()
        self.assertEqual(detail["billed_total"], "50000.00")
        self.assertEqual(detail["payment_schedule"][0]["bill"]["reference"], bill["reference"])

        # A billed order can't be sent back or cancelled.
        self.assertEqual(self.transition(order["id"], "reject", self.finance, reason="x").status_code, 400)

    def test_draft_orders_cannot_be_billed(self):
        order = self.create_order()
        response = self.record(category=self.vendor_services.id, description="x", purchase_order=order["id"], amount="10")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only approved or received", str(response.json()))


class DashboardFinancialsTests(ExpenseTestCase):
    def setUp(self):
        super().setUp()
        content = Content.objects.create(name="Decor")
        for when, amount, paid in [(date(2026, 10, 5), "115000.00", True), (date(2026, 10, 20), "57500.00", False), (date(2026, 8, 1), "11500.00", True)]:
            invoice = CustomerInvoice.objects.create(
                customer=self.event.customer, plan=self.event.plan, event=self.event,
                status=CustomerInvoice.Status.PAID if paid else CustomerInvoice.Status.UNPAID,
            )
            InvoiceLines.objects.create(invoice=invoice, content=content, inclusive_price=Decimal(amount))  # 15% VAT inclusive
            CustomerInvoice.objects.filter(pk=invoice.pk).update(date=when)

        order = self.approved_order(order_date="2026-10-10")  # 91,000 untaxed, 101,800 payable
        self.record(category=self.vendor_services.id, description="Catering deposit", purchase_order=order["id"],
                    date="2026-10-12", amount="40000.00", tax="10900.00")
        self.record(category=self.fuel.id, description="Office generator fuel", date="2026-10-15", amount="2000.00")
        self.record(category=self.fuel.id, description="Old", date="2026-08-15", amount="999.00")

    def test_income_expense_and_net_for_the_range(self):
        self.client.force_authenticate(self.boss)
        data = self.client.get("/api/v1/crm/sales/dashboard/?start_date=2026-10-01&end_date=2026-10-31").json()["data"]["financials"]
        self.assertEqual(data["income"], "150000.00")  # 100,000 + 50,000, VAT excluded
        self.assertEqual(data["collected"], "100000.00")
        self.assertEqual((data["event_costs"], data["overhead"], data["expense"]), ("40000.00", "2000.00", "42000.00"))
        self.assertEqual(data["net"], "108000.00")
        self.assertEqual(data["margin"], 72.0)
        # 101,800 − 50,900 billed leaves half of the 91,000 untaxed still to come.
        self.assertEqual(data["unbilled_commitments"], "45500.00")

        everything = self.client.get("/api/v1/crm/sales/dashboard/").json()["data"]["financials"]
        self.assertEqual((everything["income"], everything["expense"]), ("160000.00", "42999.00"))

    def test_sales_do_not_see_company_financials(self):
        self.client.force_authenticate(self.sales)
        self.assertIsNone(self.client.get("/api/v1/crm/sales/dashboard/").json()["data"]["financials"])
