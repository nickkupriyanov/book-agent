from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import UserNote

DUNE_ID = "10000000-0000-0000-0000-000000000001"
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")


def test_note_crud_for_library_book(client: TestClient) -> None:
    assert client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    ).status_code == 201

    created = client.post(
        "/api/notes",
        json={"book_id": DUNE_ID, "content": "Политика и экология Арракиса"},
    )
    assert created.status_code == 201
    note_id = created.json()["id"]
    assert created.json()["revision"] == 1
    assert client.get(f"/api/notes/{note_id}").json()["content"].startswith(
        "Политика"
    )
    assert [note["id"] for note in client.get("/api/notes").json()] == [note_id]

    updated = client.put(
        f"/api/notes/{note_id}",
        json={"book_id": DUNE_ID, "content": "Власть, экология и религия"},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2

    deleted = client.delete(f"/api/notes/{note_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/notes/{note_id}").status_code == 404


def test_note_requires_book_in_current_users_library(client: TestClient) -> None:
    response = client.post(
        "/api/notes",
        json={"book_id": DUNE_ID, "content": "Недоступная привязка"},
    )

    assert response.status_code == 409
    assert client.get("/api/notes").json() == []


def test_other_users_note_is_not_visible(
    client: TestClient,
    session: Session,
) -> None:
    note = UserNote(user_id=OTHER_USER_ID, content="Чужая точная заметка")
    session.add(note)
    session.commit()

    assert client.get(f"/api/notes/{note.id}").status_code == 404
    assert client.put(
        f"/api/notes/{note.id}",
        json={"content": "Попытка изменения"},
    ).status_code == 404
    assert client.delete(f"/api/notes/{note.id}").status_code == 404
    assert client.get("/api/notes").json() == []


def test_structured_preferences_are_upserted_separately(
    client: TestClient,
) -> None:
    first = client.put(
        "/api/preferences/genres",
        json={"value": ["history", "science_fiction"]},
    )
    second = client.put(
        "/api/preferences/genres",
        json={"value": ["history"]},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get("/api/preferences").json() == [second.json()]


def test_unknown_note_and_invalid_payload_are_rejected(client: TestClient) -> None:
    assert client.get(f"/api/notes/{uuid4()}").status_code == 404
    assert client.post("/api/notes", json={"content": ""}).status_code == 422
    assert client.post(
        "/api/notes",
        json={"content": "ok", "user_id": str(OTHER_USER_ID)},
    ).status_code == 422
