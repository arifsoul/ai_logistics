"""Runnable check for AI config resolution. `python tests/test_ai_config.py`"""

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VARS = (
    "API_KEY",
    "GROQ_API_KEY",
    "AI_BASE_URL",
    "AI_MODEL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
)

def load(**env):
    """Reload backend.ai_config with exactly the given AI env vars set."""
    # Ignore any real .env so defaults are actually exercised
    with patch("dotenv.load_dotenv"):
        import backend.ai_config as ai_config

        for name in VARS:
            os.environ.pop(name, None)
        os.environ.update(env)
        return importlib.reload(ai_config)

class TestAiConfig(unittest.TestCase):
    def setUp(self):
        self._saved = {n: os.environ.get(n) for n in VARS}

    def tearDown(self):
        for name, value in self._saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value

    def test_env_wins(self):
        cfg = load(
            API_KEY="k1",
            AI_BASE_URL="http://localhost:11434/v1",
            AI_MODEL="qwen3",
            EMBEDDING_MODEL="nomic-embed-text",
            EMBEDDING_DIM="768",
        )
        self.assertEqual(cfg.API_KEY, "k1")
        self.assertEqual(cfg.AI_BASE_URL, "http://localhost:11434/v1")
        self.assertEqual(cfg.AI_MODEL, "qwen3")
        self.assertEqual(cfg.EMBEDDING_MODEL, "nomic-embed-text")
        self.assertEqual(cfg.EMBEDDING_DIM, 768)

    def test_groq_key_is_fallback(self):
        self.assertEqual(load(GROQ_API_KEY="legacy").API_KEY, "legacy")
        self.assertEqual(load(API_KEY="new", GROQ_API_KEY="legacy").API_KEY, "new")

    def test_defaults(self):
        cfg = load(API_KEY="k1")
        self.assertEqual(
            cfg.AI_BASE_URL, "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.assertEqual(cfg.AI_MODEL, "gemini-flash-latest")
        self.assertEqual(cfg.EMBEDDING_MODEL, "gemini-embedding-001")
        self.assertEqual(cfg.EMBEDDING_DIM, 3072)

    def test_client_requires_key(self):
        with self.assertRaises(RuntimeError):
            load().openai_client()

if __name__ == "__main__":
    unittest.main()
