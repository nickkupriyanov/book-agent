from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LibraryEntry, UserNote, UserPreference


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def has_library_book(self, user_id: UUID, book_id: UUID) -> bool:
        return self.session.get(LibraryEntry, (user_id, book_id)) is not None

    def create_note(self, note: UserNote) -> UserNote:
        self.session.add(note)
        self.session.commit()
        self.session.refresh(note)
        return note

    def get_note(self, user_id: UUID, note_id: UUID) -> UserNote | None:
        return self.session.scalar(
            select(UserNote).where(
                UserNote.id == note_id,
                UserNote.user_id == user_id,
            )
        )

    def list_notes(self, user_id: UUID) -> list[UserNote]:
        return list(
            self.session.scalars(
                select(UserNote)
                .where(UserNote.user_id == user_id)
                .order_by(UserNote.updated_at.desc(), UserNote.id)
            )
        )

    def save_note(self, note: UserNote) -> UserNote:
        self.session.commit()
        self.session.refresh(note)
        return note

    def delete_note(self, note: UserNote) -> None:
        self.session.delete(note)
        self.session.commit()

    def list_preferences(self, user_id: UUID) -> list[UserPreference]:
        return list(
            self.session.scalars(
                select(UserPreference)
                .where(UserPreference.user_id == user_id)
                .order_by(UserPreference.key)
            )
        )

    def upsert_preference(
        self,
        user_id: UUID,
        key: str,
        value: object,
    ) -> UserPreference:
        preference = self.session.get(UserPreference, (user_id, key))
        if preference is None:
            preference = UserPreference(user_id=user_id, key=key, value=value)
            self.session.add(preference)
        else:
            preference.value = value
        self.session.commit()
        self.session.refresh(preference)
        return preference
