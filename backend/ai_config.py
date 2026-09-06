"""Central AI provider config, read from `.env` + DB `app_settings`.

Any OpenAI-compatible endpoint works (Google AI Studio, Groq, OpenAI,
OpenRouter, Ollama, vLLM, LM Studio, ...): point `AI_BASE_URL` /
`EMBEDDING_BASE_URL` at its `/v1` root. Chat and embeddings can use different
providers — set each base URL independently in Admin tab or `.env`.
"""

import os

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY") or os.getenv("GROQ_API_KEY")
AI_API_KEY = os.getenv("AI_API_KEY") or API_KEY
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or AI_API_KEY
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", AI_BASE_URL)
AI_MODEL = os.getenv("AI_MODEL", "gemini-flash-latest")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "3072"))

# Known embedding dims for auto-adjust (dim = output size)
EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "gemini-embedding-001": 3072,
    "gemini-embedding-exp-03-07": 3072,
    "nomic-embed-text": 768,
    "all-MiniLM-L6-v2": 384,
    "bge-small-en-v1.5": 384,
    "bge-base-en-v1.5": 768,
    "bge-large-en-v1.5": 1024,
    "e5-small-v2": 384,
    "e5-base-v2": 768,
    "e5-large-v2": 1024,
}

def embedding_dim_for(model: str) -> int | None:
    return EMBEDDING_DIMS.get(model) or EMBEDDING_DIMS.get(model.lower())

if not API_KEY and not AI_API_KEY:
    print("WARNING: API_KEY / AI_API_KEY not found in environment variables.")

def _db_settings():
    try:
        from backend.database import SessionLocal
        from backend.models_db import AppSettings
        db = SessionLocal()
        try:
            return db.query(AppSettings).filter(AppSettings.id == 1).first()
        finally:
            db.close()
    except Exception:
        return None

def effective_ai_base_url() -> str:
    s = _db_settings()
    return (s.ai_base_url if s and s.ai_base_url else None) or AI_BASE_URL

def effective_embedding_base_url() -> str:
    s = _db_settings()
    return (s.embedding_base_url if s and s.embedding_base_url else None) or EMBEDDING_BASE_URL

def effective_ai_api_key() -> str | None:
    s = _db_settings()
    if s and getattr(s, "ai_api_key", None):
        return s.ai_api_key  # type: ignore
    return AI_API_KEY or API_KEY

def effective_embedding_api_key() -> str | None:
    s = _db_settings()
    if s and getattr(s, "embedding_api_key", None):
        return s.embedding_api_key  # type: ignore
    return EMBEDDING_API_KEY or AI_API_KEY or API_KEY

def effective_ai_model() -> str:
    s = _db_settings()
    return (s.ai_model if s and s.ai_model else None) or AI_MODEL

def effective_embedding_model() -> str:
    s = _db_settings()
    return (s.embedding_model if s and s.embedding_model else None) or EMBEDDING_MODEL

def effective_embedding_dim() -> int:
    s = _db_settings()
    return (s.embedding_dim if s and s.embedding_dim else None) or EMBEDDING_DIM

def openai_client(base_url: str | None = None, api_key: str | None = None):
    key = api_key or effective_ai_api_key()
    if not key:
        raise RuntimeError("API_KEY not found in environment variables or DB")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base_url or effective_ai_base_url())

def embedding_client(base_url: str | None = None, api_key: str | None = None):
    key = api_key or effective_embedding_api_key()
    if not key:
        raise RuntimeError("EMBEDDING_API_KEY not found in environment variables or DB")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base_url or effective_embedding_base_url())
