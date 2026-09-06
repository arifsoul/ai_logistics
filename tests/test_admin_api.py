import unittest
from types import SimpleNamespace

from backend import main
from backend.models import UserResponse
from backend.roles import (
    CANONICAL_SUPERADMIN_USERNAME,
    can_delete_user,
    validate_superadmin_username,
    validate_superadmin_password,
    validate_role_change,
)


class AdminApiTests(unittest.TestCase):
    def test_admin_routes_expose_user_response_schema(self):
        self.assertIs(main.UserResponse, UserResponse)

    def test_only_canonical_username_can_keep_superadmin_role(self):
        superadmin = SimpleNamespace(
            username=CANONICAL_SUPERADMIN_USERNAME, role="superadmin"
        )
        other_user = SimpleNamespace(username="other@example.com", role="admin")

        with self.assertRaises(ValueError):
            validate_role_change(superadmin, other_user, "superadmin")

        with self.assertRaises(ValueError):
            validate_role_change(superadmin, superadmin, "admin")

    def test_superadmin_can_change_or_delete_noncanonical_accounts(self):
        superadmin = SimpleNamespace(
            id=1, username=CANONICAL_SUPERADMIN_USERNAME, role="superadmin"
        )
        other_user = SimpleNamespace(id=2, username="other@example.com", role="admin")

        self.assertEqual("user", validate_role_change(superadmin, other_user, "user"))
        self.assertTrue(can_delete_user(superadmin, other_user))

    def test_canonical_superadmin_cannot_be_deleted(self):
        superadmin = SimpleNamespace(
            id=1, username=CANONICAL_SUPERADMIN_USERNAME, role="superadmin"
        )

        self.assertFalse(can_delete_user(superadmin, superadmin))

    def test_only_canonical_username_can_be_provisioned_as_superadmin(self):
        self.assertEqual(
            CANONICAL_SUPERADMIN_USERNAME,
            validate_superadmin_username(CANONICAL_SUPERADMIN_USERNAME),
        )
        with self.assertRaises(ValueError):
            validate_superadmin_username("another@example.com")

    def test_superadmin_password_is_validated_for_database_seeding(self):
        self.assertEqual("secret", validate_superadmin_password("secret"))
        with self.assertRaises(ValueError):
            validate_superadmin_password("123")


if __name__ == "__main__":
    unittest.main()