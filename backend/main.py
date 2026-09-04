from fastapi import FastAPI, HTTPException, Depends, Form, status
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
    UserListResponse,
    UserRoleUpdate,
)
from backend.database import engine, Base, get_db, SessionLocal
from backend.models_db import User, ChatSession
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
from backend.ai_config import AI_BASE_URL, AI_MODEL, openai_client
from backend.analytics import LogisticsAnalytics
from backend import ddl_docs, history, sql_agent

# Create Tables
Base.metadata.create_all(bind=engine)

app = FastAPI()
analytics = LogisticsAnalytics()


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
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS visible_password VARCHAR"
            )
        )

    # Seed Superadmin
    super_username = os.getenv("SUPER_USERNAME")
    super_password = os.getenv("SUPER_PASSWORD")

    if super_username and super_password:
        # Get a new db session
        db = SessionLocal()
        try:
            # Check if superadmin exists
            existing_superadmin = (
                db.query(User).filter(User.username == super_username).first()
            )

            hashed_pwd = get_password_hash(super_password)

            if not existing_superadmin:
                print(f"Seeding Superadmin: {super_username}")
                new_user = User(
                    username=super_username,
                    hashed_password=hashed_pwd,
                    visible_password=super_password,
                    role="superadmin",
                )
                db.add(new_user)
            else:
                # Force update password to ensure .env is source of truth
                print(f"Updating Superadmin password and role for: {super_username}")
                existing_superadmin.hashed_password = hashed_pwd
                existing_superadmin.visible_password = super_password
                existing_superadmin.role = "superadmin"

            db.commit()
        except Exception as e:
            print(f"Error seeding superadmin: {e}")
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
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

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
            async for frame in sql_agent.answer(request.message, db, request.model):
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


@app.get("/api/models")
async def get_models():
    """Fetches available models from the configured OpenAI-compatible endpoint."""
    try:
        models = openai_client().models.list()

        # Gemini returns ids as "models/<name>"; strip it so ids match AI_MODEL.
        model_list = [
            {
                "id": m.id.removeprefix("models/"),
                "owned_by": getattr(m, "owned_by", "") or "",
            }
            for m in models.data
        ]
        return {"models": model_list, "default": AI_MODEL}
    except Exception as e:
        # Fallback so the UI still has the configured model selectable
        print(f"Error fetching models: {e}")
        return {"models": [{"id": AI_MODEL, "owned_by": AI_BASE_URL}], "default": AI_MODEL}


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
    db: Session = Depends(get_db),
):
    """
    Public registration for standard users.
    """
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Block registration of SUPER_USERNAME
    super_username = os.getenv("SUPER_USERNAME")
    if super_username and username == super_username:
        raise HTTPException(
            status_code=400, detail="This username is reserved. Please log in directly."
        )

    hashed_pwd = get_password_hash(password)
    # Default role is 'user'
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
    if role == "superadmin" and current_user.role != "superadmin":
        raise HTTPException(
            status_code=403, detail="Only Superadmin can create Superadmin"
        )

    if role not in ["user", "admin", "superadmin"]:
        raise HTTPException(status_code=400, detail="Invalid role")

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

    # Validation
    if new_role not in ["user", "admin", "superadmin"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    if current_user.role != "superadmin":
        # Regular Admin restrictions
        if target_user.role == "superadmin":
            raise HTTPException(status_code=403, detail="Cannot modify Superadmin")
        if new_role == "superadmin":
            raise HTTPException(status_code=403, detail="Cannot promote to Superadmin")

    target_user.role = new_role
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

    if target_user.role == "superadmin" and current_user.role != "superadmin":
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

    The superadmin account (SUPER_USERNAME) is never deletable: it is the only
    guaranteed way back into the admin UI. Self-deletion is refused too.
    """
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if target_user.role == "superadmin":
        raise HTTPException(status_code=403, detail="Cannot delete Superadmin")
    if target_user.username == os.getenv("SUPER_USERNAME"):
        raise HTTPException(status_code=403, detail="Cannot delete Superadmin")
    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    username = target_user.username
    # chat_sessions.user_id is a plain FK: drop the sessions through the ORM so
    # the message cascade runs, then the user row is free.
    for session in db.query(ChatSession).filter(ChatSession.user_id == user_id):
        db.delete(session)
    db.delete(target_user)
    db.commit()
    return {"status": "success", "deleted": username}

@app.get("/")
async def root():
    """The UI is the Next.js app in frontend/; this process is API-only."""
    return {"status": "ok", "service": "logistics-api", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    from backend.runtime import resolve_bind_port

    host = os.getenv("HOST", "127.0.0.1")
    port = resolve_bind_port(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
