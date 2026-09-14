from uuid import UUID, uuid4

from app.memory.exceptions import NoteBookNotInLibraryError, NoteNotFoundError
from app.memory.repository import MemoryRepository
from app.memory.retrieval import NoteSearchHit, build_note_chunks, rank_chunks
from app.models import UserNote, UserPreference


class MemoryService:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def _validate_book(self, user_id: UUID, book_id: UUID | None) -> None:
        if book_id is not None and not self.repository.has_library_book(
            user_id,
            book_id,
        ):
            raise NoteBookNotInLibraryError(book_id)

    def create_note(
        self,
        user_id: UUID,
        content: str,
        book_id: UUID | None = None,
    ) -> UserNote:
        self._validate_book(user_id, book_id)
        note = UserNote(
            id=uuid4(),
            user_id=user_id,
            book_id=book_id,
            content=content,
        )
        note.chunks = build_note_chunks(note)
        return self.repository.create_note(note)

    def get_note(self, user_id: UUID, note_id: UUID) -> UserNote:
        note = self.repository.get_note(user_id, note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        return note

    def list_notes(self, user_id: UUID) -> list[UserNote]:
        return self.repository.list_notes(user_id)

    def update_note(
        self,
        user_id: UUID,
        note_id: UUID,
        content: str,
        book_id: UUID | None = None,
    ) -> UserNote:
        note = self.get_note(user_id, note_id)
        self._validate_book(user_id, book_id)
        note.content = content
        note.book_id = book_id
        note.revision += 1
        self.repository.replace_note_chunks(note, build_note_chunks(note))
        return self.repository.save_note(note)

    def delete_note(self, user_id: UUID, note_id: UUID) -> None:
        self.repository.delete_note(self.get_note(user_id, note_id))

    def list_preferences(self, user_id: UUID) -> list[UserPreference]:
        return self.repository.list_preferences(user_id)

    def set_preference(
        self,
        user_id: UUID,
        key: str,
        value: object,
    ) -> UserPreference:
        return self.repository.upsert_preference(user_id, key, value)

    def search_notes(
        self,
        user_id: UUID,
        query: str,
        limit: int = 5,
    ) -> list[NoteSearchHit]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return rank_chunks(
            self.repository.list_chunks(user_id),
            query,
            limit,
        )
