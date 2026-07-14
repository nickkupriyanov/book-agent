from uuid import uuid4

from fastapi.testclient import TestClient

DUNE_ID = "10000000-0000-0000-0000-000000000001"


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_is_case_insensitive(client: TestClient) -> None:
    response = client.get("/api/books/search", params={"q": "дЮнА"})

    assert response.status_code == 200
    assert [book["title"] for book in response.json()] == ["Дюна"]


def test_add_list_and_update_book(client: TestClient) -> None:
    add_response = client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "reading"},
    )
    assert add_response.status_code == 201
    assert add_response.json()["status"] == "reading"

    list_response = client.get("/api/library", params={"status": "reading"})
    assert list_response.status_code == 200
    assert [entry["book"]["title"] for entry in list_response.json()] == ["Дюна"]

    update_response = client.patch(
        f"/api/library/{DUNE_ID}/status",
        json={"status": "finished"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "finished"

    assert client.get("/api/library", params={"status": "reading"}).json() == []


def test_duplicate_book_returns_conflict(client: TestClient) -> None:
    payload = {"book_id": DUNE_ID, "status": "want_to_read"}

    assert client.post("/api/library", json=payload).status_code == 201
    response = client.post("/api/library", json=payload)

    assert response.status_code == 409
    assert len(client.get("/api/library").json()) == 1


def test_unknown_book_does_not_change_library(client: TestClient) -> None:
    response = client.post(
        "/api/library",
        json={"book_id": str(uuid4()), "status": "want_to_read"},
    )

    assert response.status_code == 404
    assert client.get("/api/library").json() == []


def test_unknown_library_entry_returns_not_found(client: TestClient) -> None:
    response = client.patch(
        f"/api/library/{DUNE_ID}/status",
        json={"status": "finished"},
    )

    assert response.status_code == 404


def test_invalid_status_returns_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/library",
        json={"book_id": DUNE_ID, "status": "abandoned"},
    )

    assert response.status_code == 422
    assert client.get("/api/library").json() == []


def test_search_limit_is_validated(client: TestClient) -> None:
    assert client.get("/api/books/search", params={"q": "a", "limit": 0}).status_code == 422
    assert client.get("/api/books/search", params={"q": "a", "limit": 51}).status_code == 422
