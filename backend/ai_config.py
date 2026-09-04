"""Central AI provider config, read from `.env`.

Any OpenAI-compatible endpoint works (Google AI Studio, Groq, OpenAI,
OpenRouter, Ollama, vLLM, LM Studio, ...): point `AI_BASE_URL` at its `/v1`
root. Chat and embeddings share `API_KEY` and `AI_BASE_URL`.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# GROQ_API_KEY kept as fallback so existing .env files keep working.
API_KEY = os.getenv("API_KEY") or os.getenv("GROQ_API_KEY")
AI_BASE_URL = os.getenv(
    "AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
)
AI_MODEL = os.getenv("AI_MODEL", "gemini-flash-latest")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
# Vector width of EMBEDDING_MODEL. gemini-embedding-001 -> 3072. Override when
# swapping providers (text-embedding-3-small -> 1536), then re-seed schema_docs.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "3072"))

if not API_KEY:
    print("WARNING: API_KEY not found in environment variables.")


def openai_client():
    """OpenAI SDK client pointed at AI_BASE_URL. Raises if API_KEY is unset."""
    if not API_KEY:
        raise RuntimeError("API_KEY not found in environment variables")

    from openai import OpenAI

    return OpenAI(api_key=API_KEY, base_url=AI_BASE_URL)
