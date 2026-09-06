from fastapi import FastAPI, HTTPException, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import timedelta

import os
import sys
from pathlib import Path

# Allow `python backend/main.py` from any cwd: the project root must be
# importable so `backend.*` and the CSV seed path resolve.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from backend.models import (
    AnalyticsQueryRequest,
    AnalyticsAskRequest,
    ChatRequest,
    ForecastRequest,
    UserResponse,
    UserListResponse,
    UserRoleUpdate,
)
from backend.database import engine, Base, get_db, SessionLocal
from backend.models_db import AppSettings, User, ChatSession
from backend.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_superadmin,
    get_current_admin,
    get_password_hash,
    verify_password,
    get_current_user,
)

import json
import secrets
import uuid
from datetime import date
from backend.ai_config import AI_API_KEY, AI_BASE_URL, AI_MODEL, EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_DIM, EMBEDDING_DIMS, EMBEDDING_MODEL, effective_ai_api_key, effective_ai_base_url, effective_ai_model, effective_embedding_api_key, effective_embedding_base_url, effective_embedding_dim, effective_embedding_model, embedding_client, embedding_dim_for, openai_client
from backend.analytics import LogisticsAnalytics
from backend import ddl_docs, history, sql_agent
from backend.cors import get_allowed_origins
from backend.roles import (
    ALLOWED_ROLES,
    CANONICAL_SUPERADMIN_USERNAME,
    can_delete_user,
    is_canonical_superadmin,
    validate_superadmin_username,
    validate_role_change,
)

app = FastAPI()
analytics = LogisticsAnalytics()

# Create tables lazily — don't crash import if DATABASE_URL not set (HF Space without vars)
try:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
except Exception as _e:
    print(f"DB create_all skipped at import: {_e}")


def parse_optional_date(value: str | None):
    return date.fromisoformat(value) if value else None


@app.get("/api/analytics/kpis")
async def analytics_kpis(current_user: User = Depends(get_current_user)):
    return analytics.kpis()


@app.post("/api/analytics/query")
async def analytics_query(
    request: AnalyticsQueryRequest, current_user: User = Depends(get_current_user)
):
    try:
        return analytics.query(
            metric=request.metric,
            dimension=request.dimension,
            date_range=request.date_range,
            date_from=parse_optional_date(request.date_from),
            date_to=parse_optional_date(request.date_to),
            carrier=request.carrier,
            sku=request.sku,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/forecast")
async def forecast(
    request: ForecastRequest, current_user: User = Depends(get_current_user)
):
    try:
        return analytics.forecast(request.sku, request.horizon_months)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/analytics/ask")
async def analytics_ask(
    request: AnalyticsAskRequest, current_user: User = Depends(get_current_user)
):
    try:
        return analytics.ask(request.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.on_event("startup")
async def startup_event():
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS visible_password VARCHAR"
                )
            )
            # app_settings for admin-editable AI/embedding config
            connection.execute(text("CREATE TABLE IF NOT EXISTS app_settings (id INTEGER PRIMARY KEY, ai_base_url VARCHAR, embedding_base_url VARCHAR, ai_api_key VARCHAR, embedding_api_key VARCHAR, ai_model VARCHAR, embedding_model VARCHAR, embedding_dim INTEGER, updated_at TIMESTAMP)"))
            connection.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS ai_api_key VARCHAR"))
            connection.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS embedding_api_key VARCHAR"))
            connection.execute(text("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))
            # Make embedding column dimension-agnostic so admin can swap models without migration
            try:
                connection.execute(text("ALTER TABLE schema_docs ALTER COLUMN embedding TYPE vector"))
            except Exception:
                pass
    except Exception as _e:
        print(f"DB startup migration skipped: {_e}")

    # Keep exactly one protected superadmin identity. Password provisioning is
    # intentionally handled by `backend.seed`, never by application env vars.
    super_username = CANONICAL_SUPERADMIN_USERNAME

    db = SessionLocal()
    try:
        existing_superadmin = (
            db.query(User).filter(User.username == super_username).first()
        )
        if existing_superadmin:
            existing_superadmin.role = "superadmin"

        db.query(User).filter(
            User.role == "superadmin", User.username != super_username
        ).update({User.role: "admin"}, synchronize_session=False)
        db.commit()
    except Exception as e:
        print(f"Error normalizing superadmin: {e}")
        db.rollback()
    finally:
        db.close()

    # Refresh the text-to-SQL context. This re-reads the live column list and
    # the distinct values of every text column, so a new carrier or status that
    # appeared in the data becomes part of the RAG context on the next boot.
    # `use_llm=False` keeps startup independent of the AI provider: the column
    # purpose comments come from the cache written by the seeder. Nothing is
    # re-embedded unless the generated DDL text actually changed.
    db = SessionLocal()
    try:
        result = ddl_docs.sync(db, use_llm=False)
        if result["changed"]:
            print(f"Schema context refreshed: {result['documents']} documents")
    except Exception as e:
        print(f"Schema context refresh skipped: {e}")
    finally:
        db.close()

# CORS. An explicit origin list, not "*": `allow_credentials=True` with a
# wildcard is rejected by browsers, and the Next.js client is cross-origin.
ALLOWED_ORIGINS = get_allowed_origins(os.getenv("CORS_ORIGINS"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/chat")
async def chat_endpoint(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Text-to-SQL chat. Streams NDJSON frames, one JSON object per line.

    Frames: {"type":"sql"}, {"type":"table"}, {"type":"chart"},
    {"type":"meta"}, {"type":"token"}, {"type":"error"}, {"type":"done"}.
    """
    session_id = request.session_id or str(uuid.uuid4())

    # --- Session Isolation Check ---
    chat_session = (
        db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    )
    if chat_session:
        if chat_session.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: You do not own this chat session.",
            )
    else:
        db.add(ChatSession(session_id=session_id, user_id=current_user.id))
        db.commit()
    # -------------------------------

    from fastapi.responses import StreamingResponse

    history.add_message(db, session_id, "user", request.message)

    async def generate():
        answer_parts: list[str] = []
        payload: dict = {}
        try:
            async for frame in sql_agent.answer(request.message, db, request.model or effective_ai_model(), request.base_url):
                if frame["type"] == "token":
                    answer_parts.append(frame["text"])
                elif frame["type"] in ("sql", "chart", "table", "meta"):
                    # `table` is stored whole; the others hold their data under
                    # a key that is not always the frame type (meta -> forecast).
                    payload[frame["type"]] = (
                        frame
                        if frame["type"] in ("table", "meta")
                        else frame[frame["type"]]
                    )
                yield json.dumps(frame) + "\n"
        except Exception as error:  # never leave the stream unterminated
            print(f"Streaming Error: {error}")
            yield json.dumps({"type": "error", "message": str(error)}) + "\n"
        finally:
            if answer_parts or payload:
                history.add_message(
                    db, session_id, "assistant", "".join(answer_parts), payload
                )

    # NDJSON, so the client can parse each frame as it arrives.
    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _is_embedding_model_id(mid: str) -> bool:
    m = mid.lower()
    return any(k in m for k in ("embed", "bge", "e5-", "nomic", "minilm", "gte", "uae", "instructor"))

@app.get("/api/models")
async def get_models(
    base_url: str | None = Query(default=None),
    kind: str = Query(default="chat"),
    api_key: str | None = Query(default=None),
):
    """Fetches available models from the configured OpenAI-compatible endpoint.

    `base_url` + `api_key` override the server defaults for this request only
    (used by Admin tab to preview before saving). `kind=embedding` filters to
    embedding models only and uses the embedding base/key.
    """
    target = base_url.strip() if base_url and base_url.strip() else None
    if target and not (target.startswith("http://") or target.startswith("https://")):
        raise HTTPException(status_code=400, detail="base_url must start with http:// or https://")
    is_emb = kind == "embedding"
    default_model = effective_embedding_model() if is_emb else effective_ai_model()
    default_base = effective_embedding_base_url() if is_emb else effective_ai_base_url()
    # api_key override: explicit query param > DB > env
    override_key = api_key.strip() if api_key and api_key.strip() else None
    try:
        if is_emb:
            key = override_key or effective_embedding_api_key()
            base = target or default_base
            client = embedding_client(base_url=base, api_key=key) if key else embedding_client(base_url=base)
        else:
            key = override_key or effective_ai_api_key()
            base = target or default_base
            client = openai_client(base_url=base, api_key=key) if key else openai_client(base_url=base)
        models = client.models.list()
        model_list = [
            {"id": m.id.removeprefix("models/"), "owned_by": getattr(m, "owned_by", "") or ""}
            for m in models.data
        ]
        if is_emb:
            # Filter to embedding models only; if none match, return all (provider may not tag them)
            filtered = [x for x in model_list if _is_embedding_model_id(x["id"])]
            if filtered:
                model_list = filtered
        return {"models": model_list, "default": default_model, "base_url": target or default_base}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching models: {e}")
        fallback_base = target or default_base
        return {"models": [{"id": default_model, "owned_by": fallback_base}], "default": default_model, "base_url": fallback_base}

@app.get("/api/models/validate")
async def validate_model(
    model: str = Query(...),
    kind: str = Query(default="chat"),
    base_url: str | None = Query(default=None),
    api_key: str | None = Query(default=None),
):
    """Check if a model id exists at the target endpoint. Returns {valid, models}."""
    target = base_url.strip() if base_url and base_url.strip() else None
    override_key = api_key.strip() if api_key and api_key.strip() else None
    is_emb = kind == "embedding"
    try:
        if is_emb:
            key = override_key or effective_embedding_api_key()
            base = target or effective_embedding_base_url()
            client = embedding_client(base_url=base, api_key=key) if key else embedding_client(base_url=base)
        else:
            key = override_key or effective_ai_api_key()
            base = target or effective_ai_base_url()
            client = openai_client(base_url=base, api_key=key) if key else openai_client(base_url=base)
        models = client.models.list()
        ids = {m.id.removeprefix("models/") for m in models.data}
        # also accept with prefix
        raw_ids = {m.id for m in models.data}
        valid = model in ids or model in raw_ids
        return {"valid": valid, "model": model, "kind": kind, "base_url": target or base}
    except Exception as e:
        return {"valid": False, "model": model, "kind": kind, "error": str(e)}

@app.get("/api/ai-config")
async def get_ai_config(current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    # has_key flags so UI knows if env/DB provides a key without leaking it
    has_ai_key = bool((row.ai_api_key if row and getattr(row, "ai_api_key", None) else None) or AI_API_KEY or os.getenv("API_KEY"))
    has_emb_key = bool((row.embedding_api_key if row and getattr(row, "embedding_api_key", None) else None) or EMBEDDING_API_KEY or AI_API_KEY or os.getenv("API_KEY"))
    return {
        "ai_base_url": (row.ai_base_url if row and row.ai_base_url else None) or AI_BASE_URL,
        "embedding_base_url": (row.embedding_base_url if row and row.embedding_base_url else None) or EMBEDDING_BASE_URL,
        "ai_model": (row.ai_model if row and row.ai_model else None) or AI_MODEL,
        "embedding_model": (row.embedding_model if row and row.embedding_model else None) or EMBEDDING_MODEL,
        "embedding_dim": (row.embedding_dim if row and row.embedding_dim else None) or EMBEDDING_DIM,
        "has_ai_api_key": has_ai_key,
        "has_embedding_api_key": has_emb_key,
        "defaults": {"ai_base_url": AI_BASE_URL, "embedding_base_url": EMBEDDING_BASE_URL, "ai_model": AI_MODEL, "embedding_model": EMBEDDING_MODEL, "embedding_dim": EMBEDDING_DIM},
        "embedding_dims": EMBEDDING_DIMS,
    }

@app.put("/api/ai-config")
async def put_ai_config(payload: dict, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not row:
        row = AppSettings(id=1)
        db.add(row)
    for key in ("ai_base_url", "embedding_base_url", "ai_model", "embedding_model"):
        if key in payload and payload[key] is not None:
            v = str(payload[key]).strip()
            if v and not (v.startswith("http://") or v.startswith("https://")) and "base_url" in key:
                raise HTTPException(status_code=400, detail=f"{key} must start with http:// or https://")
            setattr(row, key, v or None)
    # api keys: empty string clears DB override (falls back to env)
    for key in ("ai_api_key", "embedding_api_key"):
        if key in payload and payload[key] is not None:
            v = str(payload[key]).strip()
            setattr(row, key, v or None)
    if "embedding_dim" in payload and payload["embedding_dim"] is not None:
        try:
            row.embedding_dim = int(payload["embedding_dim"])
        except Exception:
            raise HTTPException(status_code=400, detail="embedding_dim must be integer")
    # auto-adjust dim if model known and dim not explicitly set to a different value
    if "embedding_model" in payload and payload["embedding_model"]:
        auto = embedding_dim_for(str(payload["embedding_model"]).strip())
        if auto and ("embedding_dim" not in payload or payload["embedding_dim"] is None):
            row.embedding_dim = auto
        elif auto and "embedding_dim" in payload:
            # if user picked a known model, suggest its dim (still allow override)
            pass
    # validate models exist at target endpoints (non-blocking warning if unreachable)
    for kind, model_key, base_key, key_key in [
        ("chat", "ai_model", "ai_base_url", "ai_api_key"),
        ("embedding", "embedding_model", "embedding_base_url", "embedding_api_key"),
    ]:
        if model_key in payload and payload[model_key]:
            mid = str(payload[model_key]).strip()
            base = str(payload.get(base_key, "") or getattr(row, base_key, "") or "").strip() or None
            k = str(payload.get(key_key, "") or getattr(row, key_key, "") or "").strip() or None
            try:
                if kind == "embedding":
                    c = embedding_client(base_url=base or effective_embedding_base_url(), api_key=k or effective_embedding_api_key())
                else:
                    c = openai_client(base_url=base or effective_ai_base_url(), api_key=k or effective_ai_api_key())
                ids = {m.id.removeprefix("models/") for m in c.models.list().data}
                raw = {m.id for m in c.models.list().data} if False else set()  # placeholder
                if mid not in ids and mid not in raw:
                    # try once more with raw ids
                    c2 = c.models.list()
                    all_ids = {m.id.removeprefix("models/") for m in c2.data} | {m.id for m in c2.data}
                    if mid not in all_ids:
                        raise HTTPException(status_code=400, detail=f"Model '{mid}' not found at {base or 'configured base URL'} for kind={kind}")
            except HTTPException:
                raise
            except Exception:
                # provider unreachable — allow save, validation will happen on use
                pass
    db.commit()
    db.refresh(row)
    return {"status": "ok", "ai_base_url": row.ai_base_url or AI_BASE_URL, "embedding_base_url": row.embedding_base_url or EMBEDDING_BASE_URL, "ai_model": row.ai_model or AI_MODEL, "embedding_model": row.embedding_model or EMBEDDING_MODEL, "embedding_dim": row.embedding_dim or EMBEDDING_DIM}

@app.post("/api/ai-config/sync")
async def sync_ai_config(payload: dict | None = None, current_user: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Save config (if payload) then re-embed schema_docs with current embedding model/base_url."""
    payload = payload or {}
    row = db.query(AppSettings).filter(AppSettings.id == 1).first()
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    has_update = any(k in payload for k in ("ai_base_url", "embedding_base_url", "ai_model", "embedding_model", "embedding_dim", "ai_api_key", "embedding_api_key"))
    if has_update:
        for key in ("ai_base_url", "embedding_base_url", "ai_model", "embedding_model"):
            if key in payload and payload[key] is not None:
                v = str(payload[key]).strip()
                if v and not (v.startswith("http://") or v.startswith("https://")) and "base_url" in key:
                    raise HTTPException(status_code=400, detail=f"{key} must start with http:// or https://")
                setattr(row, key, v or None)
        for key in ("ai_api_key", "embedding_api_key"):
            if key in payload and payload[key] is not None:
                v = str(payload[key]).strip()
                setattr(row, key, v or None)
        if "embedding_dim" in payload and payload["embedding_dim"] is not None:
            try:
                row.embedding_dim = int(payload["embedding_dim"])
            except Exception:
                raise HTTPException(status_code=400, detail="embedding_dim must be integer")
        elif "embedding_model" in payload and payload["embedding_model"]:
            auto = embedding_dim_for(str(payload["embedding_model"]).strip())
            if auto:
                row.embedding_dim = auto
        db.commit()
        db.refresh(row)
    emb_base = row.embedding_base_url or EMBEDDING_BASE_URL
    emb_model = row.embedding_model or EMBEDDING_MODEL
    result = ddl_docs.sync(db, force=True, use_llm=False)
    return {"status": "ok", "documents": result.get("documents", 0), "embedding_model": emb_model, "embedding_base_url": emb_base, "embedding_dim": row.embedding_dim or EMBEDDING_DIM}


@app.get("/api/history/{session_id}")
async def get_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the chat history for a specific session."""
    # --- Session Isolation Check ---
    chat_session = (
        db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    )
    if not chat_session:
        # Unknown id: reveal nothing, but don't break a fresh UI either.
        return {"history": []}

    if chat_session.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Access denied: You do not own this chat session."
        )
    # -------------------------------

    return {"history": history.get_history(db, session_id)}


@app.delete("/api/history/{session_id}")
async def delete_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes the chat history for a specific session."""
    # --- Session Isolation Check ---
    chat_session = (
        db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    )
    if chat_session:
        if chat_session.user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: You do not own this chat session.",
            )

        # Messages go too, via ON DELETE CASCADE on chat_messages.session_id.
        db.delete(chat_session)
        db.commit()
        return {"status": "success", "message": "History deleted"}
    # -------------------------------

    return {"status": "warning", "message": "Session not found"}


# --- Auth Endpoints ---


@app.post("/api/auth/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}


@app.post("/api/auth/register-superadmin")
async def register_superadmin(
    username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)
):
    """
    Initial setup endpoint.
    Only works if no superadmin exists yet.
    """
    existing_superadmin = db.query(User).filter(User.role == "superadmin").first()
    if existing_superadmin:
        raise HTTPException(status_code=400, detail="Superadmin already exists")

    try:
        username = validate_superadmin_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    hashed_pwd = get_password_hash(password)
    new_user = User(
        username=username,
        hashed_password=hashed_pwd,
        visible_password=password,
        role="superadmin",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"username": new_user.username, "role": new_user.role}


@app.post("/api/auth/register-admin")
async def register_admin(
    username: str = Form(...),
    password: str = Form(...),
    current_user: User = Depends(get_current_superadmin),
    db: Session = Depends(get_db),
):
    """
    Create a new Admin. Only Superadmin can do this.
    """
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_pwd = get_password_hash(password)
    new_user = User(
        username=username,
        hashed_password=hashed_pwd,
        visible_password=password,
        role="admin",
    )
    db.add(new_user)
    db.commit()
    return {"username": new_user.username, "role": new_user.role}


@app.get("/api/users/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
    }


@app.post("/api/auth/register")
async def register_user(
    username: str = Form(...),
    password: str = Form(...),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Registration locked to admin/superadmin. Public self-register disabled.
    Use /api/users for admin creation; this endpoint kept for admin UI compat.
    """
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    if username.casefold() == CANONICAL_SUPERADMIN_USERNAME:
        raise HTTPException(
            status_code=400, detail="This username is reserved. Please log in directly."
        )

    hashed_pwd = get_password_hash(password)
    new_user = User(
        username=username,
        hashed_password=hashed_pwd,
        visible_password=password,
        role="user",
    )
    db.add(new_user)
    db.commit()
    return {"username": new_user.username, "role": new_user.role}


@app.get("/api/users", response_model=UserListResponse)
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List all users. Restricted to Admins and Superadmins.
    """
    users = db.query(User).offset(skip).limit(limit).all()
    return {
        "users": [
            UserResponse(
                id=user.id,
                username=user.username,
                role=user.role,
                password=user.visible_password,
            )
            for user in users
        ]
    }


@app.post("/api/users")
async def create_user(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Admin/Superadmin create user.
    """
    # Check permissions
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    if role == "superadmin" and (
        current_user.role != "superadmin" or username.casefold() != CANONICAL_SUPERADMIN_USERNAME
    ):
        raise HTTPException(status_code=403, detail="Only super@admin.com may be Superadmin")

    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_pwd = get_password_hash(password)
    new_user = User(
        username=username,
        hashed_password=hashed_pwd,
        visible_password=password,
        role=role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "username": new_user.username,
        "role": new_user.role,
        "password": new_user.visible_password,
    }


@app.put("/api/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    role_update: UserRoleUpdate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Update user role.
    - Superadmin can update anyone.
    - Admin can only update 'user' <-> 'admin'.
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    new_role = role_update.role

    try:
        target_user.role = validate_role_change(current_user, target_user, new_role)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    db.commit()
    return {
        "status": "success",
        "username": target_user.username,
        "role": target_user.role,
    }


@app.post("/api/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Issue a new password and return it once.

    Stored passwords are argon2 hashes, so an existing one cannot be read back.
    This is the supported way for a user manager to hand a password over: the
    plaintext exists only in this response.
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if is_canonical_superadmin(target_user):
        raise HTTPException(status_code=403, detail="Cannot modify Superadmin")

    new_password = secrets.token_urlsafe(9)
    target_user.hashed_password = get_password_hash(new_password)
    target_user.visible_password = new_password
    db.commit()
    return {
        "status": "success",
        "username": target_user.username,
        "password": new_password,
    }

@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Delete a user and their chat history.

    The canonical superadmin account is never deletable: it is the only
    guaranteed way back into the admin UI. Self-deletion is refused too.
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not can_delete_user(current_user, target_user):
        raise HTTPException(status_code=403, detail="Cannot delete this account")

    username = target_user.username
    # chat_sessions.user_id is a plain FK: drop the sessions through the ORM so
    # the message cascade runs, then the user row is free.
    for session in db.query(ChatSession).filter(ChatSession.user_id == user_id):
        db.delete(session)
    db.delete(target_user)
    db.commit()
    return {"status": "success", "deleted": username}

FRONTEND_URL_DEFAULT = "https://logistics-ai.netlify.app/"

def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", FRONTEND_URL_DEFAULT).rstrip("/") + "/"

_LANDING_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Logistics Analytics API</title>
<style>
  *{box-sizing:border-box} body{margin:0;min-height:100vh;display:grid;place-items:center;background:#020617;color:#e2e8f0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .card{width:min(560px,92vw);background:#0f172a;border:1px solid #1e293b;border-radius:16px;padding:32px;text-align:center;box-shadow:0 10px 30px rgba(0,0,0,.4)}
  h1{margin:0 0 8px;font-size:22px} p{margin:0;color:#94a3b8;line-height:1.5}
  .btn{display:inline-block;margin:20px 0 14px;padding:12px 22px;border-radius:10px;background:#06b6d4;color:#020617;font-weight:700;text-decoration:none}
  .btn:hover{background:#22d3ee} .links{font-size:13px} .links a{color:#7dd3fc;text-decoration:none} .links a:hover{text-decoration:underline}
  code{background:#1e293b;padding:2px 6px;border-radius:6px;font-size:12px;color:#cbd5e1}
</style>
</head>
<body>
  <div class="card">
    <h1>📦 Logistics Analytics API</h1>
    <p>Backend running on Hugging Face. UI ada di Netlify — klik tombol di bawah untuk buka aplikasi.</p>
    <a class="btn" href="{frontend_url}" target="_blank" rel="noopener noreferrer">Buka Aplikasi → logistics-ai.netlify.app</a>
    <p class="links"><a href="/docs">API Docs</a> · <a href="/health">Health</a> · <a href="/health/db">DB Health</a> · <code>GET /</code> JSON jika Accept: application/json</p>
  </div>
</body>
</html>"""

def _landing_html() -> str:
    return _LANDING_HTML_TEMPLATE.format(frontend_url=_frontend_url())

@app.get("/")
async def root(request: Request):
    """Landing HTML for browsers (Hugging Face), JSON for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return HTMLResponse(content=_landing_html())
    return {"status": "ok", "service": "logistics-api", "docs": "/docs", "frontend": _frontend_url()}


@app.get("/health")
async def health():
    """Liveness probe — does not require DB."""
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    """DB connectivity probe."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "up"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db down: {e}")


if __name__ == "__main__":
    import uvicorn

    from backend.runtime import resolve_bind_port

    host = os.getenv("HOST", "127.0.0.1")
    port = resolve_bind_port(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
