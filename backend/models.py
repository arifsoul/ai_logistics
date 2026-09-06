from pydantic import BaseModel
from typing import List, Optional

from backend.ai_config import effective_ai_model


class ChatRequest(BaseModel):
    message: str
    session_id: str
    model: str | None = None
    base_url: str | None = None


class ChatResponse(BaseModel):
    response: str
    sources: List[str] = []


class UploadResponse(BaseModel):
    filename: str
    status: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    password: Optional[str] = None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: List[UserResponse]


class UserRoleUpdate(BaseModel):
    role: str


class AnalyticsQueryRequest(BaseModel):
    metric: str
    dimension: str
    date_range: str = "all"
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    carrier: Optional[str] = None
    sku: Optional[str] = None


class ForecastRequest(BaseModel):
    sku: str
    horizon_months: int = 4


class AnalyticsAskRequest(BaseModel):
    question: str
