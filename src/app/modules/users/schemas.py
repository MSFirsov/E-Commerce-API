from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None
    role: UserRole
    created_at: datetime
