from uuid import UUID


class BookNotFoundError(Exception):
    def __init__(self, book_id: UUID) -> None:
        super().__init__(f"Book {book_id} was not found")


class LibraryEntryNotFoundError(Exception):
    def __init__(self, book_id: UUID) -> None:
        super().__init__(f"Book {book_id} is not in the user's library")


class DuplicateLibraryEntryError(Exception):
    def __init__(self, book_id: UUID) -> None:
        super().__init__(f"Book {book_id} is already in the user's library")
