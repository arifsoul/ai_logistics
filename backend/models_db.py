"""SQLAlchemy models. Everything lives in one Postgres database (Supabase).

Two groups:
- app tables: `users`, `chat_sessions`, `chat_messages`
- data + retrieval: `orders` (the analytics dataset) and `schema_docs`
  (pgvector embeddings of the `orders` schema, used to ground text-to-SQL)
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    visible_password = Column(String, nullable=True)
    role = Column(
        String
    )  # 'superadmin', 'admin', 'user' (optional, mainly for admin features)

    sessions = relationship("ChatSession", back_populates="user")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True)  # UUID from frontend
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """Chat transcript. Replaces the LangGraph SQLite checkpointer.

    `payload` carries the structured answer for assistant turns: the executed
    SQL, the result table and the chart spec, so a reloaded session renders
    exactly what was streamed the first time.
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        String, ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), index=True
    )
    role = Column(String)  # 'user' | 'assistant'
    content = Column(Text)
    payload = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class Order(Base):
    """One row per logistics order, loaded from `mock_logistics_data.csv`.

    This is the only table the text-to-SQL agent is allowed to read.
    """

    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    client_id = Column(String, index=True)
    order_date = Column(Date, index=True)
    delivery_date = Column(Date, nullable=True)
    carrier = Column(String, index=True)
    origin_city = Column(String)
    destination_city = Column(String)
    status = Column(String, index=True)
    sku = Column(String, index=True)
    product_category = Column(String, index=True)
    quantity = Column(Integer)
    unit_price_usd = Column(Numeric(10, 2))
    order_value_usd = Column(Numeric(12, 2))
    is_promo = Column(Boolean)
    promo_discount_pct = Column(Integer)
    region = Column(String, index=True)
    warehouse = Column(String, index=True)


class SchemaDoc(Base):
    """Embedded description of the `orders` table or one of its columns.

    Retrieved by cosine distance to ground the SQL planner in the real schema.
    """

    __tablename__ = "schema_docs"

    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True)  # "orders" or "orders.carrier"
    content = Column(Text)
    # ponytail: no HNSW index — this table holds ~20 rows, so an exact scan is
    # already sub-millisecond. Add an index (and an embedding <=2000 dims) if
    # the corpus ever grows past a few thousand rows.
    # Vector dim left open so admin can swap embedding models without migration.
    embedding = Column(Vector)

class AppSettings(Base):
    """Singleton row (id=1) for admin-editable AI/Embedding config."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    ai_base_url = Column(String, nullable=True)
    embedding_base_url = Column(String, nullable=True)
    ai_api_key = Column(String, nullable=True)
    embedding_api_key = Column(String, nullable=True)
    ai_model = Column(String, nullable=True)
    embedding_model = Column(String, nullable=True)
    embedding_dim = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

