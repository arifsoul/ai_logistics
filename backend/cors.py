from __future__ import annotations


DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://logistics-ai.netlify.app",
)


def get_allowed_origins(configured: str | None) -> list[str]:
    """Return stable local/production origins plus configured frontend origins."""
    origins: list[str] = []
    for origin in (*DEFAULT_ALLOWED_ORIGINS, *(configured or "").split(",")):
        normalized = origin.strip().rstrip("/")
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins