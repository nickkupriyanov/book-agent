from uuid import UUID


class NoteNotFoundError(Exception):
    def __init__(self, note_id: UUID) -> None:
        super().__init__(f"Note {note_id} was not found")


class NoteBookNotInLibraryError(Exception):
    def __init__(self, book_id: UUID) -> None:
        super().__init__(
            f"Book {book_id} must be in the user's library before adding a note"
        )
