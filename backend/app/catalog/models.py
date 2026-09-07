from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class CatalogSource(str, Enum):
    LOCAL = "local"
    OPEN_LIBRARY = "open_library"


@dataclass(frozen=True)
class CatalogBook:
    id: UUID
    title: str
    author: str
    tags: tuple[str, ...]
    catalog_source: CatalogSource = CatalogSource.LOCAL
    external_id: str | None = None
    isbn: str | None = None
    cover_url: str | None = None


@dataclass(frozen=True)
class CatalogSearchResult:
    books: tuple[CatalogBook, ...]
    source: CatalogSource
    degraded: bool = False
    cached: bool = False
