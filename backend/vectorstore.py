"""pgvector-backed retrieval of `orders` schema metadata."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai_config import effective_embedding_model, embedding_client
from backend.models_db import SchemaDoc

def embed_texts(texts: list[str], base_url: str | None = None, model: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    m = model or effective_embedding_model()
    response = embedding_client(base_url=base_url).embeddings.create(
        model=m, input=texts, encoding_format="float"
    )
    return [item.embedding for item in response.data]

def replace_schema_docs(db: Session, docs: dict[str, str], base_url: str | None = None, model: str | None = None) -> int:
    refs = list(docs)
    vectors = embed_texts([docs[ref] for ref in refs], base_url=base_url, model=model)
    db.query(SchemaDoc).delete()
    db.add_all(SchemaDoc(ref=ref, content=docs[ref], embedding=vector) for ref, vector in zip(refs, vectors))
    db.commit()
    return len(refs)

def search_schema(db: Session, question: str, k: int = 8) -> list[SchemaDoc]:
    vector = embed_texts([question])[0]
    stmt = select(SchemaDoc).order_by(SchemaDoc.embedding.cosine_distance(vector)).limit(k)
    return list(db.scalars(stmt))

def get_doc(db: Session, ref: str) -> str | None:
    return db.scalar(select(SchemaDoc.content).where(SchemaDoc.ref == ref))

def schema_context(db: Session, question: str, k: int = 8, exclude: str | None = None) -> str:
    docs = search_schema(db, question, k + (1 if exclude else 0))
    if not docs:
        docs = list(db.scalars(select(SchemaDoc)))
    if exclude:
        docs = [doc for doc in docs if doc.ref != exclude][:k]
    return "\n\n".join(f"[{doc.ref}]\n{doc.content}" for doc in docs)
