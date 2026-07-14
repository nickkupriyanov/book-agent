from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models import ReadingStatus


class HealthResponse(BaseModel):
    status: str


class BookResponse(BaseModel):
    id: UUID
    title: str
    author: str

    model_config = ConfigDict(from_attributes=True)


class LibraryEntryCreate(BaseModel):
    book_id: UUID
    status: ReadingStatus


class LibraryStatusUpdate(BaseModel):
    status: ReadingStatus


class LibraryEntryResponse(BaseModel):
    book: BookResponse
    status: ReadingStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
