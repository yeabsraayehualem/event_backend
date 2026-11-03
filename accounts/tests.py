from rest_framework.test import APITestCase

from accounts.models import User
from hr.models import Employee

BASE = "/api/v1/user"


def make(role, phone, **extra):
    return User.objects.create_user(username=phone, phone=phone, password="Strong-pass-123", role=role, **extra)


class UserAdminTests(APITestCase):
    def setUp(self):
        self.root = make(User.Role.SUPER, "0900000001")
        self.admin = make(User.Role.ADMIN, "0900000002")
        self.sales = make(User.Role.SALES, "0900000003")

    def test_only_admins_manage_users(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(self.client.get(f"{BASE}/users/").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f"{BASE}/users/").status_code, 200)

    def test_create_with_temporary_password_and_sign_in(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"{BASE}/users/", {"phone": "0911223344", "first_name": "Hana", "last_name": "Girma", "role": "finance"}, format="json")
        self.assertEqual(response.status_code, 201, response.json())
        temporary = response.json()["temporary_password"]
        self.assertEqual(len(temporary), 12)
        self.client.force_authenticate(None)
        login = self.client.post(f"{BASE}/login/", {"phone": "0911223344", "password": temporary}, format="json")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["data"]["role"], "finance")

    def test_weak_password_and_duplicate_phone_are_rejected(self):
        self.client.force_authenticate(self.admin)
        weak = self.client.post(f"{BASE}/users/", {"phone": "0911", "role": "sales", "password": "123"}, format="json")
        self.assertEqual(weak.status_code, 400)
        self.assertIn("password", weak.json())
        duplicate = self.client.post(f"{BASE}/users/", {"phone": self.sales.phone, "role": "sales"}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_admins_cannot_touch_super_users(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"{BASE}/users/", {"phone": "0922", "role": "super"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.sales.id}/", {"role": "super"}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.root.id}/", {"is_active": False}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"{BASE}/users/{self.root.id}/password/", {}, format="json").status_code, 403)
        self.assertNotIn("super", [role["value"] for role in self.client.get(f"{BASE}/users/options/").json()["roles"]])

    def test_no_self_demotion_and_a_super_user_always_remains(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.admin.id}/", {"role": "sales"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.admin.id}/", {"is_active": False}, format="json").status_code, 400)

        other = make(User.Role.SUPER, "0900000009")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.root.id}/", {"role": "admin"}, format="json").status_code, 200)
        last = self.client.patch(f"{BASE}/users/{self.root.id}/", {"role": "super"}, format="json")
        self.assertEqual(last.status_code, 200)
        self.client.force_authenticate(self.root)
        self.client.patch(f"{BASE}/users/{other.id}/", {"is_active": False}, format="json")
        self.assertFalse(User.objects.get(pk=other.pk).is_active)
        # root is now the only active super user and can't step down (self-rule) — and nobody else can demote them.
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f"{BASE}/users/{self.root.id}/", {"role": "admin"}, format="json").status_code, 403)

    def test_deactivated_users_cannot_sign_in_and_changes_are_logged(self):
        self.client.force_authenticate(self.admin)
        self.client.patch(f"{BASE}/users/{self.sales.id}/", {"is_active": False, "role": "finance"}, format="json")
        log = self.client.get(f"/api/v1/chatter/user/{self.sales.id}/").json()[0]["tracking_values"]
        self.assertEqual({(t["field"], t["new_value"]) for t in log}, {("is_active", "False"), ("role", "Finance")})
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"{BASE}/login/", {"phone": self.sales.phone, "password": "Strong-pass-123"}, format="json").status_code, 401)

    def test_link_to_crew_record(self):
        crew = Employee.objects.create(full_name="Sara Tesfaye", phone="0955")
        self.client.force_authenticate(self.admin)
        response = self.client.patch(f"{BASE}/users/{self.sales.id}/", {"employee_id": crew.id}, format="json")
        self.assertEqual(response.json()["employee"], {"id": crew.id, "full_name": "Sara Tesfaye"})
        taken = self.client.post(f"{BASE}/users/", {"phone": "0933", "role": "hr", "employee_id": crew.id}, format="json")
        self.assertIn("already linked", str(taken.json()))
        self.client.patch(f"{BASE}/users/{self.sales.id}/", {"employee_id": None}, format="json")
        self.assertIsNone(Employee.objects.get(pk=crew.pk).user_id)

    def test_reset_and_change_own_password(self):
        self.client.force_authenticate(self.admin)
        temporary = self.client.post(f"{BASE}/users/{self.sales.id}/password/", {}, format="json").json()["temporary_password"]
        self.sales.refresh_from_db()
        self.assertTrue(self.sales.check_password(temporary))

        self.client.force_authenticate(self.sales)
        wrong = self.client.post(f"{BASE}/profile/password/", {"current_password": "nope", "new_password": "Another-pass-456"}, format="json")
        self.assertEqual(wrong.status_code, 400)
        ok = self.client.post(f"{BASE}/profile/password/", {"current_password": temporary, "new_password": "Another-pass-456"}, format="json")
        self.assertEqual(ok.status_code, 200)
        self.sales.refresh_from_db()
        self.assertTrue(self.sales.check_password("Another-pass-456"))
