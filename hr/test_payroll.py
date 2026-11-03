from datetime import date
from decimal import Decimal

from accounts.models import User
from finance.models import Expense
from hr.models import IncomeTaxBracket, income_tax
from hr.tests import BASE, HRTestCase, at


class TaxTableTests(HRTestCase):
    def test_marginal_tax_matches_the_official_shortcut(self):
        brackets = list(IncomeTaxBracket.objects.all())
        # The published "rate × income − deduction" figures for each band.
        for income, expected in [(1500, "0.00"), (3000, "150.00"), (5000, "500.00"), (8000, "1150.00"), (12000, "2250.00"), (15000, "3200.00")]:
            self.assertEqual(income_tax(Decimal(income), brackets), Decimal(expected), income)


class PayRunTests(HRTestCase):
    def setUp(self):
        super().setUp()
        self.boss = User.objects.create_user(username="boss", phone="0900000009", password="pass", role=User.Role.SUPER)
        self.sara = self.add_employee(full_name="Sara Tesfaye", phone="0955", employment_type="permanent", wage_basis="monthly",
                                      rate="15000", payment_account="CBE 1000123", skill_ids=[])
        self.abebe = self.add_employee(payment_account="")
        # Two worked shifts (1 day and 2 days at 800/day), one still scheduled.
        for start, end, status in [(at(10, 8), at(10, 20), "completed"), (at(19, 8), at(20, 20), "completed"), (at(25, 8), at(25, 20), None)]:
            shift = self.book(self.abebe["id"], self.events[2], start, end, allow_conflict=True).json()
            if status:
                self.client.patch(f"{BASE}/shifts/{shift['id']}/", {"status": status}, format="json")
        self.client.force_authenticate(self.hr)

    def generate(self, period="2027-01"):
        return self.client.post(f"{BASE}/pay-runs/", {"period": period}, format="json")

    def slip(self, run, name):
        return next(slip for slip in run["payslips"] if slip["employee_name"] == name)

    def act(self, run, action, user, **extra):
        self.client.force_authenticate(user)
        return self.client.post(f"{BASE}/pay-runs/{run['id']}/transition/", {"action": action, **extra}, format="json")

    def test_generate_builds_salary_and_shift_payslips(self):
        response = self.generate()
        self.assertEqual(response.status_code, 200, response.json())
        run = response.json()
        self.assertEqual((run["reference"], run["status"]), ("PAY-2027-01", "draft"))

        sara = self.slip(run, "Sara Tesfaye")
        self.assertEqual((sara["gross"], sara["income_tax"], sara["pension_employee"], sara["pension_employer"], sara["net"]),
                         ("15000.00", "3200.00", "1050.00", "1650.00", "10750.00"))
        abebe = self.slip(run, "Abebe Kebede")
        self.assertEqual((abebe["kind"], abebe["gross"], abebe["net"], len(abebe["lines"])), ("freelance", "2400.00", "2400.00", 2))
        self.assertEqual(run["totals"]["employer_cost"], "19050.00")
        self.assertEqual({w["code"] for w in run["warnings"]}, {"tax_table", "accounts"})

        # One live run per month.
        self.assertEqual(self.generate().status_code, 400)

    def test_mid_month_starter_is_prorated(self):
        self.client.patch(f"{BASE}/employees/{self.sara['id']}/", {"hire_date": "2027-01-17"}, format="json")
        sara = self.slip(self.generate().json(), "Sara Tesfaye")
        self.assertEqual(sara["basic_salary"], "7258.06")  # 15 of 31 days
        self.assertIn("15 of 31 days", sara["lines"][0]["description"])

    def test_adjustments_and_approval_rules(self):
        run = self.generate().json()
        sara = self.slip(run, "Sara Tesfaye")
        run = self.client.post(f"{BASE}/payslips/{sara['id']}/lines/", {"kind": "earning", "description": "Holiday bonus", "amount": "1000"}, format="json").json()
        run = self.client.post(f"{BASE}/payslips/{sara['id']}/lines/", {"kind": "deduction", "description": "Salary advance", "amount": "500"}, format="json").json()
        sara = self.slip(run, "Sara Tesfaye")
        # Tax on 16,000 is 16,000 × 35% − 2,050 = 3,550; pension stays on the 15,000 basic.
        self.assertEqual((sara["gross"], sara["income_tax"], sara["pension_employee"], sara["other_deductions"], sara["net"]),
                         ("16000.00", "3550.00", "1050.00", "500.00", "10900.00"))

        self.assertEqual(self.act(run, "approve", self.hr).status_code, 403)
        blocked = self.act(run, "approve", self.finance)
        self.assertIn("tax table", str(blocked.json()))

        self.client.force_authenticate(self.hr)
        self.assertEqual(self.client.patch(f"{BASE}/payroll/rules/", {"tax_table_confirmed": True}, format="json").status_code, 403)
        self.client.force_authenticate(self.finance)
        self.client.patch(f"{BASE}/payroll/rules/", {"tax_table_confirmed": True}, format="json")
        approved = self.act(run, "approve", self.finance)
        self.assertEqual(approved.json()["status"], "approved")

        # Approved runs are locked until reopened.
        self.client.force_authenticate(self.hr)
        self.assertEqual(self.client.post(f"{BASE}/payslips/{sara['id']}/lines/", {"kind": "earning", "description": "x", "amount": "1"}, format="json").status_code, 400)

    def test_shifts_on_a_run_are_locked_and_not_paid_twice(self):
        run = self.generate().json()
        shift_id = self.slip(run, "Abebe Kebede")["lines"][0]["shift"]
        self.client.force_authenticate(self.finance)
        self.assertIn("PAY-2027-01", str(self.client.post(f"{BASE}/shifts/{shift_id}/payout/", {}, format="json").json()))
        self.client.force_authenticate(self.hr)
        self.assertEqual(self.client.patch(f"{BASE}/shifts/{shift_id}/", {"units": "3"}, format="json").status_code, 400)
        self.assertEqual(self.client.get(f"{BASE}/shifts/{shift_id}/").json()["pay_run"]["reference"], "PAY-2027-01")

    def test_paying_records_expenses_and_held_people_roll_over(self):
        run = self.generate().json()
        abebe = self.slip(run, "Abebe Kebede")
        self.client.patch(f"{BASE}/payslips/{abebe['id']}/", {"held": True}, format="json")
        self.client.force_authenticate(self.finance)
        self.client.patch(f"{BASE}/payroll/rules/", {"tax_table_confirmed": True}, format="json")
        self.act(run, "approve", self.finance)

        csv = self.client.get(f"{BASE}/pay-runs/{run['id']}/bank-file/").content.decode("utf-8-sig").splitlines()
        self.assertEqual(csv[1], "1,Sara Tesfaye,0955,CBE 1000123,10750.00,PAY-2027-01 Salary")
        self.assertEqual(len(csv), 2)

        paid = self.act(run, "pay", self.finance, paid_on="2027-01-31", payment_method="bank_transfer").json()
        self.assertEqual((paid["status"], paid["paid_on"], len(paid["payslips"])), ("paid", "2027-01-31", 1))
        salary = Expense.objects.get(source=Expense.Source.PAYROLL)
        self.assertEqual((salary.amount, salary.event, salary.category.name, salary.date), (Decimal("16650.00"), None, "Salaries", date(2027, 1, 31)))
        self.assertEqual(self.client.delete(f"/api/v1/finance/expenses/{salary.id}/").status_code, 400)

        # Abebe was held, so his shifts go on February's run.
        self.client.force_authenticate(self.hr)
        february = self.generate("2027-02").json()
        self.assertEqual(self.slip(february, "Abebe Kebede")["gross"], "2400.00")

    def test_paid_freelance_shifts_become_event_costs(self):
        run = self.generate().json()
        self.client.force_authenticate(self.finance)
        self.client.patch(f"{BASE}/payroll/rules/", {"tax_table_confirmed": True}, format="json")
        self.act(run, "approve", self.finance)
        self.act(run, "pay", self.finance)
        crew = Expense.objects.filter(source=Expense.Source.CREW_PAYOUT)
        self.assertEqual(sorted(e.amount for e in crew), [Decimal("800.00"), Decimal("1600.00")])
        self.assertTrue(all(e.event_id == self.events[2].id and e.shift_id for e in crew))

    def test_changing_the_tax_table_needs_confirming_again(self):
        self.client.force_authenticate(self.finance)
        self.client.patch(f"{BASE}/payroll/rules/", {"tax_table_confirmed": True}, format="json")
        bad = self.client.patch(f"{BASE}/payroll/rules/", {"brackets": [{"upper_limit": "5000", "rate": "10"}, {"upper_limit": "3000", "rate": "20"}, {"upper_limit": None, "rate": "30"}]}, format="json")
        self.assertEqual(bad.status_code, 400)
        rules = self.client.patch(f"{BASE}/payroll/rules/", {"brackets": [{"upper_limit": "2000", "rate": "0"}, {"upper_limit": None, "rate": "10"}]}, format="json").json()
        self.assertFalse(rules["tax_table_confirmed"])
        self.assertEqual(len(rules["brackets"]), 2)
