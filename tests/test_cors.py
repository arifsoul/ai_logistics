import unittest

from backend.cors import get_allowed_origins


class CorsConfigurationTests(unittest.TestCase):
    def test_defaults_include_local_and_production_frontends(self):
        origins = get_allowed_origins(None)

        self.assertIn("http://localhost:3000", origins)
        self.assertIn("http://127.0.0.1:3000", origins)
        self.assertIn("https://logistics-ai.netlify.app", origins)

    def test_configured_origins_are_trimmed_and_deduplicated(self):
        origins = get_allowed_origins(
            " https://logistics-ai.netlify.app/ , https://example.com, https://example.com/ "
        )

        self.assertEqual(
            [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "https://logistics-ai.netlify.app",
                "https://example.com",
            ],
            origins,
        )


if __name__ == "__main__":
    unittest.main()