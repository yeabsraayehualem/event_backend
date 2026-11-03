from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import User
from crm.models import Customers, Lead
from event.models import Event, Plan
from hr.models import Employee, Skill

BASE = "/api/v1/hr"


def at(day, hour):
    return timezone.make_aware(datetime(2027, 1, day, hour)).isoformat()


class HRTestCase(APITestCase):
    def setUp(self):
        self.hr = User.objects.create_user(username="hr", phone="0900000001", password="pass", role=User.Role.HR)
        self.finance = User.objects.create_user(username="fin", phone="0900000002", password="pass", role=User.Role.FINANCE)
        self.sales = User.objects.create_user(username="sales", phone="0900000003", password="pass", role=User.Role.SALES)
        plan = Plan.objects.create(name="Wedding")
        self.events = []
        for index, day in enumerate((10, 10, 20)):
            customer = Customers.objects.create(name=f"C{index}", phone=f"091{index}")
            lead = Lead.objects.create(customer=customer, plan=plan, plan_date=date(2027, 1, day), location="Addis")
            self.events.append(Event.objects.create(lead=lead, customer=customer, plan=plan, name=f"Event {index}", event_date=date(2027, 1, day), location="Addis"))
        self.usher = Skill.objects.get(name="Usher")
        self.client.force_authenticate(self.hr)

    def add_employee(self, **overrides):
        payload = {"full_name": "Abebe Kebede", "phone": "0944", "employment_type": "freelance", "wage_basis": "daily",
                   "rate": "800.00", "skill_ids": [self.usher.id], **overrides}
        response = self.client.post(f"{BASE}/employees/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        return response.json()

    def book(self, employee_id, event, start, end, **extra):
        return self.client.post(f"{BASE}/shifts/", {"employee": employee_id, "event": event.id, "start": start, "end": end, **extra}, format="json")


class DirectoryTests(HRTestCase):
    def test_access(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(self.client.get(f"{BASE}/employees/").status_code, 403)
        self.client.force_authenticate(self.finance)
        self.assertEqual(self.client.get(f"{BASE}/employees/").status_code, 200)
        self.assertEqual(self.client.post(f"{BASE}/employees/", {"full_name": "x", "phone": "1"}, format="json").status_code, 403)

    def test_filter_by_skill_basis_and_verification(self):
        abebe = self.add_employee()
        self.add_employee(full_name="Sara", phone="0955", employment_type="permanent", wage_basis="monthly", rate="15000", skill_ids=[])
        self.client.patch(f"{BASE}/employees/{abebe['id']}/", {"id_verified": True}, format="json")
        names = lambda query: [e["full_name"] for e in self.client.get(f"{BASE}/employees/?{query}").json()]
        self.assertEqual(names(f"skill={self.usher.id}"), ["Abebe Kebede"])
        self.assertEqual(names("wage_basis=monthly"), ["Sara"])
        self.assertEqual(names("verified=true"), ["Abebe Kebede"])

    def test_freelancers_cannot_be_monthly(self):
        response = self.client.post(f"{BASE}/employees/", {"full_name": "X", "phone": "0966", "employment_type": "freelance", "wage_basis": "monthly"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_rate_change_is_tracked(self):
        abebe = self.add_employee()
        self.client.patch(f"{BASE}/employees/{abebe['id']}/", {"rate": "900.00"}, format="json")
        change = self.client.get(f"/api/v1/chatter/employee/{abebe['id']}/").json()[0]["tracking_values"][0]
        self.assertEqual((change["old_value"], change["new_value"]), ("800.00", "900.00"))


class SchedulingTests(HRTestCase):
    def test_booking_copies_pay_terms_and_counts_days(self):
        abebe = self.add_employee()
        response = self.book(abebe["id"], self.events[2], at(19, 8), at(20, 23))
        self.assertEqual(response.status_code, 201, response.json())
        shift = response.json()
        self.assertEqual((shift["role"], shift["wage_basis"], shift["rate"], shift["units"], shift["amount"]), ("Usher", "daily", "800.00", "2.00", "1600.00"))

        # Later rate changes don't rewrite the booking.
        self.client.patch(f"{BASE}/employees/{abebe['id']}/", {"rate": "1000.00"}, format="json")
        self.assertEqual(self.client.get(f"{BASE}/shifts/{shift['id']}/").json()["rate"], "800.00")

    def test_overlapping_bookings_are_flagged(self):
        abebe = self.add_employee()
        self.assertEqual(self.book(abebe["id"], self.events[0], at(10, 8), at(10, 18)).status_code, 201)
        clash = self.book(abebe["id"], self.events[1], at(10, 16), at(10, 23))
        self.assertEqual(clash.status_code, 400)
        self.assertEqual(clash.json()["conflicts"][0]["event_name"], "Event 0")
        # Back-to-back is fine, and a clash can be accepted on purpose.
        self.assertEqual(self.book(abebe["id"], self.events[1], at(10, 18), at(10, 23)).status_code, 201)
        forced = self.book(abebe["id"], self.events[1], at(10, 9), at(10, 10), allow_conflict=True)
        self.assertEqual(forced.status_code, 201)
        self.assertEqual(len(forced.json()["conflicts"]), 1)

    def test_cancelled_shifts_free_the_slot(self):
        abebe = self.add_employee()
        first = self.book(abebe["id"], self.events[0], at(10, 8), at(10, 18)).json()
        self.client.patch(f"{BASE}/shifts/{first['id']}/", {"status": "cancelled"}, format="json")
        self.assertEqual(self.book(abebe["id"], self.events[1], at(10, 8), at(10, 18)).status_code, 201)

    def test_end_must_follow_start(self):
        abebe = self.add_employee()
        self.assertEqual(self.book(abebe["id"], self.events[0], at(10, 18), at(10, 8)).status_code, 400)


class PayoutTests(HRTestCase):
    def worked_shift(self, **employee):
        person = self.add_employee(**employee)
        shift = self.book(person["id"], self.events[2], at(20, 8), at(20, 23)).json()
        self.client.patch(f"{BASE}/shifts/{shift['id']}/", {"status": "completed"}, format="json")
        return shift

    def test_paying_a_shift_records_an_event_expense(self):
        shift = self.worked_shift()
        self.assertEqual(self.client.post(f"{BASE}/shifts/{shift['id']}/payout/", {}, format="json").status_code, 403)

        self.client.force_authenticate(self.finance)
        response = self.client.post(f"{BASE}/shifts/{shift['id']}/payout/", {"payment_method": "mobile_money"}, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        payout = response.json()["payout"]
        expense = self.client.get(f"/api/v1/finance/expenses/{payout['id']}/").json()
        self.assertEqual((expense["amount"], expense["event"], expense["category_name"], expense["source"]),
                         ("800.00", self.events[2].id, "Freelance crew", "crew_payout"))

        # Paid once, then locked.
        self.assertEqual(self.client.post(f"{BASE}/shifts/{shift['id']}/payout/", {}, format="json").status_code, 400)
        self.client.force_authenticate(self.hr)
        self.assertEqual(self.client.patch(f"{BASE}/shifts/{shift['id']}/", {"units": "3"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"{BASE}/shifts/{shift['id']}/").status_code, 400)

        # The payout's amount can't drift from the shift.
        self.client.force_authenticate(self.finance)
        self.assertEqual(self.client.patch(f"/api/v1/finance/expenses/{payout['id']}/", {"amount": "1"}, format="json").status_code, 400)

        # Deleting the expense makes the shift payable again.
        self.client.delete(f"/api/v1/finance/expenses/{payout['id']}/")
        self.assertIsNone(self.client.get(f"{BASE}/shifts/{shift['id']}/").json()["payout"])

    def test_only_worked_freelance_shifts_are_paid(self):
        person = self.add_employee()
        shift = self.book(person["id"], self.events[2], at(20, 8), at(20, 23)).json()
        self.client.force_authenticate(self.finance)
        self.assertIn("Mark the shift as worked", str(self.client.post(f"{BASE}/shifts/{shift['id']}/payout/", {}, format="json").json()))

        self.client.force_authenticate(self.hr)
        salaried = self.worked_shift(full_name="Sara", phone="0955", employment_type="permanent", wage_basis="monthly", rate="15000")
        self.assertEqual(salaried["amount"], "0.00")
        self.client.force_authenticate(self.finance)
        self.assertIn("covered by payroll", str(self.client.post(f"{BASE}/shifts/{salaried['id']}/payout/", {}, format="json").json()))

    def test_payout_shows_on_the_employee(self):
        shift = self.worked_shift()
        self.client.force_authenticate(self.finance)
        self.client.post(f"{BASE}/shifts/{shift['id']}/payout/", {}, format="json")
        employee = self.client.get(f"{BASE}/employees/{shift['employee']}/").json()
        self.assertEqual((employee["totals"]["events_worked"], employee["totals"]["paid_total"]), (1, "800.00"))
        self.assertEqual(Employee.objects.get().rate, Decimal("800.00"))
