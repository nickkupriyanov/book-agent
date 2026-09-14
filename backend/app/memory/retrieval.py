import hashlib
import re
from dataclasses import dataclass
from uuid import UUID, NAMESPACE_URL, uuid5

from app.models import NoteChunk, UserNote

WORD_PATTERN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in WORD_PATTERN.finditer(text))


def chunk_text(
    text: str,
    *,
    max_words: int = 80,
    overlap_words: int = 16,
) -> tuple[str, ...]:
    if max_words < 1:
        raise ValueError("max_words must be at least 1")
    if overlap_words < 0 or overlap_words >= max_words:
        raise ValueError("overlap_words must be between 0 and max_words - 1")

    words = text.split()
    if not words:
        return ()
    if len(words) <= max_words:
        return (" ".join(words),)

    chunks: list[str] = []
    step = max_words - overlap_words
    for start in range(0, len(words), step):
        chunk_words = words[start : start + max_words]
        chunks.append(" ".join(chunk_words))
        if start + max_words >= len(words):
            break
    return tuple(chunks)


def build_note_chunks(note: UserNote) -> list[NoteChunk]:
    chunks = chunk_text(note.content)
    content_digest = hashlib.sha256(note.content.encode("utf-8")).hexdigest()
    return [
        NoteChunk(
            id=uuid5(
                NAMESPACE_URL,
                f"book-agent:note-chunk:{note.id}:{content_digest}:{position}",
            ),
            note_id=note.id,
            user_id=note.user_id,
            book_id=note.book_id,
            position=position,
            content=content,
            token_count=len(tokenize(content)),
        )
        for position, content in enumerate(chunks)
    ]


@dataclass(frozen=True)
class NoteSearchHit:
    chunk_id: UUID
    note_id: UUID
    book_id: UUID | None
    fragment: str
    score: float


def rank_chunks(
    chunks: list[NoteChunk],
    query: str,
    limit: int,
) -> list[NoteSearchHit]:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []

    hits: list[NoteSearchHit] = []
    for chunk in chunks:
        overlap = query_tokens.intersection(tokenize(chunk.content))
        if not overlap:
            continue
        hits.append(
            NoteSearchHit(
                chunk_id=chunk.id,
                note_id=chunk.note_id,
                book_id=chunk.book_id,
                fragment=chunk.content,
                score=len(overlap) / len(query_tokens),
            )
        )
    hits.sort(key=lambda hit: (-hit.score, str(hit.chunk_id)))
    return hits[:limit]
