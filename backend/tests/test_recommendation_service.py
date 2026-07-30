from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.exceptions import BookNotFoundError
from app.models import ReadingStatus
from app.repository import BookRepository
from app.service import BookService

DUNE_ID = UUID("10000000-0000-0000-0000-000000000001")
NINETEEN_EIGHTY_FOUR_ID = UUID("10000000-0000-0000-0000-000000000002")
MARTIAN_ID = UUID("10000000-0000-0000-0000-000000000003")
ATOMIC_HABITS_ID = UUID("10000000-0000-0000-0000-000000000004")
SOLARIS_ID = UUID("10000000-0000-0000-0000-000000000005")
ROADSIDE_PICNIC_ID = UUID("10000000-0000-0000-0000-000000000006")
FLOWERS_FOR_ALGERNON_ID = UUID("10000000-0000-0000-0000-000000000007")
LEFT_HAND_OF_DARKNESS_ID = UUID("10000000-0000-0000-0000-000000000008")
SAPIENS_ID = UUID("10000000-0000-0000-0000-000000000010")


def test_candidates_are_ranked_by_score_then_stable_book_id(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))

    candidates = service.find_similar_books(
        user_id=get_settings().demo_user_id,
        source_book_ids=[DUNE_ID],
        limit=4,
    )

    assert [candidate.book.id for candidate in candidates] == [
        LEFT_HAND_OF_DARKNESS_ID,
        NINETEEN_EIGHTY_FOUR_ID,
        MARTIAN_ID,
        SOLARIS_ID,
    ]
    assert candidates[0].score == 2
    assert candidates[0].matched_tags == ("politics", "science_fiction")
    assert [candidate.score for candidate in candidates[1:]] == [1, 1, 1]


def test_candidates_match_multiple_sources_without_duplicate_ids(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))

    candidates = service.find_similar_books(
        user_id=get_settings().demo_user_id,
        source_book_ids=[DUNE_ID, NINETEEN_EIGHTY_FOUR_ID, DUNE_ID],
        limit=10,
    )

    candidate_ids = [candidate.book.id for candidate in candidates]
    roadside_picnic = next(
        candidate
        for candidate in candidates
        if candidate.book.id == ROADSIDE_PICNIC_ID
    )
    assert len(candidate_ids) == len(set(candidate_ids))
    assert DUNE_ID not in candidate_ids
    assert NINETEEN_EIGHTY_FOUR_ID not in candidate_ids
    assert roadside_picnic.matched_tags == ("dystopia", "science_fiction")
    assert roadside_picnic.score == 2


def test_all_library_statuses_are_excluded_from_candidates(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id
    service.add_book(
        user_id,
        LEFT_HAND_OF_DARKNESS_ID,
        ReadingStatus.WANT_TO_READ,
    )
    service.add_book(
        user_id,
        NINETEEN_EIGHTY_FOUR_ID,
        ReadingStatus.READING,
    )
    service.add_book(
        user_id,
        MARTIAN_ID,
        ReadingStatus.FINISHED,
    )

    candidates = service.find_similar_books(
        user_id=user_id,
        source_book_ids=[DUNE_ID],
        limit=3,
    )

    assert [candidate.book.id for candidate in candidates] == [
        SOLARIS_ID,
        ROADSIDE_PICNIC_ID,
        FLOWERS_FOR_ALGERNON_ID,
    ]


def test_returns_fewer_candidates_when_matches_are_insufficient(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))

    candidates = service.find_similar_books(
        user_id=get_settings().demo_user_id,
        source_book_ids=[ATOMIC_HABITS_ID],
        limit=5,
    )

    assert [candidate.book.id for candidate in candidates] == [
        FLOWERS_FOR_ALGERNON_ID,
        SAPIENS_ID,
    ]
    assert all(candidate.score == 1 for candidate in candidates)


def test_unknown_source_book_is_rejected(session: Session) -> None:
    service = BookService(BookRepository(session))

    with pytest.raises(BookNotFoundError):
        service.find_similar_books(
            user_id=get_settings().demo_user_id,
            source_book_ids=[uuid4()],
        )


def test_empty_candidate_list_is_a_valid_result(session: Session) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id
    service.add_book(
        user_id,
        FLOWERS_FOR_ALGERNON_ID,
        ReadingStatus.WANT_TO_READ,
    )
    service.add_book(
        user_id,
        SAPIENS_ID,
        ReadingStatus.FINISHED,
    )

    candidates = service.find_similar_books(
        user_id=user_id,
        source_book_ids=[ATOMIC_HABITS_ID],
    )

    assert candidates == []


def test_empty_sources_and_invalid_limit_are_rejected(
    session: Session,
) -> None:
    service = BookService(BookRepository(session))
    user_id = get_settings().demo_user_id

    with pytest.raises(ValueError, match="source_book_ids"):
        service.find_similar_books(user_id, [])
    with pytest.raises(ValueError, match="limit"):
        service.find_similar_books(user_id, [DUNE_ID], limit=0)
