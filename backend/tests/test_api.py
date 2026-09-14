from unittest.mock import create_autospec
from uuid import uuid4

from fastapi.testclient import TestClient

from app.catalog.exceptions import CatalogUnavailableError
from app.dependencies import get_book_service
from app.main import app
from app.service import BookService

DUNE_ID = "10000000-0000-0000-0000-000000000001"


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_legacy_direct_chat_route_is_not_available(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "Расскажи о Дюне"})

    assert response.status_code == 404


def test_search_is_case_insensitive(client: TestClient) -> None:
    response = client.get("/api/books/search", params={"q": "дЮнА"})

    assert response.status_code == 200
    assert [book["title"] for book in response.json()] == ["Дюна"]


def test_get_book_by_id(client: TestClient) -> None:
    response = client.get(f"/api/books/{DUNE_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "id": DUNE_ID,
        "title": "Дюна",
        "author": "Фрэнк Герберт",
        "tags": ["politics", "science_fiction", "space_opera"],
    }


def test_get_unknown_book_returns_not_found(client: TestClient) -> None:
    book_id = uuid4()

    response = client.get(f"/api/books/{book_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": f"Book {book_id} was not found"}


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


def test_catalog_error_returns_safe_bad_gateway(client: TestClient) -> None:
    service = create_autospec(BookService, instance=True)
    service.search_books.side_effect = CatalogUnavailableError(
        "https://secret.example/internal"
    )
    app.dependency_overrides[get_book_service] = lambda: service

    response = client.get("/api/books/search", params={"q": "Dune"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Book catalog is unavailable"}
    assert "secret.example" not in response.text
