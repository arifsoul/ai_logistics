import unittest

from backend import main
from backend.models import UserResponse


class AdminApiTests(unittest.TestCase):
    def test_admin_routes_expose_user_response_schema(self):
        self.assertIs(main.UserResponse, UserResponse)


if __name__ == "__main__":
    unittest.main()