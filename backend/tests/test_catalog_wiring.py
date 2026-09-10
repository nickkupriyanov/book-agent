from collections.abc import Generator

from sqlalchemy.orm import Session

from app.catalog.local import LocalBookCatalog
from app.catalog.resilient import ResilientBookCatalog
from app.config import Settings
from app.dependencies import get_book_catalog


def open_dependency(
    dependency: Generator[object, None, None],
) -> tuple[object, Generator[object, None, None]]:
    return next(dependency), dependency


def test_catalog_dependency_keeps_local_provider_available(session: Session) -> None:
    dependency = get_book_catalog(session, Settings(catalog_provider="local"))
    catalog, dependency = open_dependency(dependency)
    try:
        assert isinstance(catalog, LocalBookCatalog)
    finally:
        dependency.close()


def test_catalog_dependency_builds_resilient_external_provider(
    session: Session,
) -> None:
    dependency = get_book_catalog(
        session,
        Settings(
            catalog_provider="open_library",
            open_library_base_url="https://catalog.example",
            open_library_timeout_seconds=0.5,
            open_library_max_retries=1,
            catalog_cache_ttl_seconds=60,
            catalog_cache_max_entries=10,
        ),
    )
    catalog, dependency = open_dependency(dependency)
    try:
        assert isinstance(catalog, ResilientBookCatalog)
    finally:
        dependency.close()
