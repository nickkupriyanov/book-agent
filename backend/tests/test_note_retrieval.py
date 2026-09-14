from uuid import UUID

from sqlalchemy.orm import Session

from app.memory.repository import MemoryRepository
from app.memory.retrieval import build_note_chunks, chunk_text
from app.memory.service import MemoryService
from app.models import NoteChunk, UserNote

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")


def test_chunking_has_bounded_overlap() -> None:
    text = " ".join(f"word-{number}" for number in range(10))

    chunks = chunk_text(text, max_words=4, overlap_words=1)

    assert chunks == (
        "word-0 word-1 word-2 word-3",
        "word-3 word-4 word-5 word-6",
        "word-6 word-7 word-8 word-9",
    )


def test_create_indexes_note_with_stable_chunk_ids(session: Session) -> None:
    service = MemoryService(MemoryRepository(session))

    note = service.create_note(USER_ID, "Экология определяет политику Арракиса")
    first_ids = [chunk.id for chunk in note.chunks]
    updated = service.update_note(USER_ID, note.id, note.content)

    assert [chunk.id for chunk in updated.chunks] == first_ids
    assert updated.chunks[0].token_count == 4


def test_update_replaces_old_chunks_and_delete_removes_them(
    session: Session,
) -> None:
    service = MemoryService(MemoryRepository(session))
    note = service.create_note(USER_ID, "Экология пустыни и власть")
    old_chunk_id = note.chunks[0].id

    updated = service.update_note(USER_ID, note.id, "Мифология и религия")

    assert session.get(NoteChunk, old_chunk_id) is None
    assert service.search_notes(USER_ID, "экология") == []
    assert service.search_notes(USER_ID, "мифология")[0].note_id == note.id

    service.delete_note(USER_ID, note.id)

    assert service.search_notes(USER_ID, "мифология") == []


def test_search_ranks_relevant_chunks_and_keeps_provenance(
    session: Session,
) -> None:
    service = MemoryService(MemoryRepository(session))
    politics = service.create_note(
        USER_ID,
        "Политика и экология связаны через контроль воды",
    )
    service.create_note(USER_ID, "Только политика империи")

    hits = service.search_notes(USER_ID, "политика экология", limit=2)

    assert hits[0].note_id == politics.id
    assert hits[0].chunk_id == politics.chunks[0].id
    assert hits[0].book_id is None
    assert hits[0].score == 1.0


def test_search_filters_by_user_before_ranking(session: Session) -> None:
    service = MemoryService(MemoryRepository(session))
    own = service.create_note(USER_ID, "Редкое совпадение")
    other = UserNote(user_id=OTHER_USER_ID, content="Редкое совпадение совпадение")
    session.add(other)
    session.flush()
    other.chunks = build_note_chunks(other)
    session.commit()

    hits = service.search_notes(USER_ID, "редкое совпадение")

    assert [hit.note_id for hit in hits] == [own.id]


def test_search_without_matching_context_is_empty(session: Session) -> None:
    service = MemoryService(MemoryRepository(session))
    service.create_note(USER_ID, "Политика и экология")

    assert service.search_notes(USER_ID, "музыка") == []
    assert service.search_notes(USER_ID, "!!!") == []
