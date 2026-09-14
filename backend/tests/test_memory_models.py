from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import NoteChunk, UserNote, UserPreference

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_note_owns_ordered_chunks(session: Session) -> None:
    note = UserNote(user_id=USER_ID, content="О власти и ответственности")
    session.add(note)
    session.flush()
    note.chunks.extend(
        [
            NoteChunk(
                id=uuid4(),
                user_id=USER_ID,
                position=1,
                content="ответственности",
                token_count=1,
            ),
            NoteChunk(
                id=uuid4(),
                user_id=USER_ID,
                position=0,
                content="О власти",
                token_count=2,
            ),
        ]
    )
    session.commit()

    session.expire_all()
    stored = session.get(UserNote, note.id)

    assert stored is not None
    assert [chunk.position for chunk in stored.chunks] == [0, 1]


def test_note_delete_cascades_to_chunks(session: Session) -> None:
    note = UserNote(user_id=USER_ID, content="Короткая заметка")
    note.chunks.append(
        NoteChunk(
            id=uuid4(),
            user_id=USER_ID,
            position=0,
            content=note.content,
            token_count=2,
        )
    )
    session.add(note)
    session.commit()
    chunk_id = note.chunks[0].id

    session.delete(note)
    session.commit()

    assert session.get(NoteChunk, chunk_id) is None


def test_preference_key_is_unique_per_user(session: Session) -> None:
    session.add(UserPreference(user_id=USER_ID, key="genres", value=["history"]))
    session.commit()
    session.add(UserPreference(user_id=USER_ID, key="genres", value=["fantasy"]))

    with pytest.raises(IntegrityError):
        session.commit()
