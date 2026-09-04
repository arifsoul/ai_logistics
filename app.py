"""Dev entry point for the API. The UI is the Next.js app in frontend/ (`npm run dev`)."""

import os

import uvicorn

from backend.runtime import resolve_bind_port


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = resolve_bind_port(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
