import unittest

from backend.runtime import resolve_bind_port


class TestServerRuntime(unittest.TestCase):
    def test_uses_requested_port_when_available(self):
        port = resolve_bind_port(8765)
        self.assertEqual(port, 8765)


if __name__ == "__main__":
    unittest.main()
