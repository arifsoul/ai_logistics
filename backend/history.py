"""Chat history in Postgres. Replaces the LangGraph SQLite checkpointer.

Each turn is a row in `chat_messages`. Assistant rows carry the structured
answer (`sql`, `table`, `chart`) in a JSONB `payload`, so reloading a session
re-renders exactly what was streamed.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models_db import ChatMessage


def add_message(
    db: Session,
    session_id: str,
    role: str,
    content: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        ChatMessage(
            session_id=session_id, role=role, content=content, payload=payload
        )
    )
    db.commit()


def get_history(db: Session, session_id: str) -> List[Dict[str, Any]]:
    """Turns oldest-first, in the shape the chat UI renders."""
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .all()
    )
    return [
        {
            "role": message.role,
            "content": message.content,
            **(message.payload or {}),
        }
        for message in messages
    ]


def delete_history(db: Session, session_id: str) -> int:
    """Delete a session's messages. Returns how many rows went away."""
    deleted = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
