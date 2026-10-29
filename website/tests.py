from decimal import Decimal

from rest_framework.test import APITestCase

from event.models import Package, Plan


class PublicPlansTests(APITestCase):
    def test_plans_include_description_and_packages_with_prices_cheapest_first(self):
        plan = Plan.objects.create(name="Wedding", description="Teklil and the celebration")
        Package.objects.create(plan=plan, name="Gold", price=Decimal("600000.00"), description="Full day")
        Package.objects.create(plan=plan, name="Quote", price=Decimal("0.00"))
        Package.objects.create(plan=plan, name="Silver", price=Decimal("250000.00"))

        [data] = self.client.get("/api/v1/website/plans/").json()

        self.assertEqual((data["description"], data["image"]), ("Teklil and the celebration", None))
        self.assertEqual([(item["name"], item["price"]) for item in data["packages"]],
                         [("Silver", "250000.00"), ("Gold", "600000.00"), ("Quote", "0.00")])
        self.assertEqual(data["packages"][1]["description"], "Full day")
