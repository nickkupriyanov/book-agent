from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import router
from app.catalog.exceptions import CatalogError
from app.agent.exceptions import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
)
from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.llm.exceptions import (
    LLMNotConfiguredError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.memory.exceptions import NoteBookNotInLibraryError, NoteNotFoundError
from app.schemas import HealthResponse

app = FastAPI(title="Book Agent API", version="0.1.0")
app.include_router(router)


@app.exception_handler(CatalogError)
def handle_catalog_error(request: Request, exc: CatalogError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "Book catalog is unavailable"},
    )


@app.exception_handler(ApprovalNotFoundError)
def handle_approval_not_found(
    request: Request,
    exc: ApprovalNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(ApprovalConflictError)
def handle_approval_conflict(
    request: Request,
    exc: ApprovalConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(ApprovalExpiredError)
def handle_approval_expired(
    request: Request,
    exc: ApprovalExpiredError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"detail": str(exc)},
    )


@app.exception_handler(LLMNotConfiguredError)
def handle_llm_not_configured(
    request: Request, exc: LLMNotConfiguredError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


@app.exception_handler(LLMTimeoutError)
def handle_llm_timeout(request: Request, exc: LLMTimeoutError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={"detail": "LLM provider timed out"},
    )


@app.exception_handler(LLMUnavailableError)
def handle_llm_unavailable(
    request: Request, exc: LLMUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "LLM provider is unavailable"},
    )


@app.exception_handler(LLMRateLimitError)
def handle_llm_rate_limit(
    request: Request, exc: LLMRateLimitError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "LLM provider rate limit exceeded"},
    )


@app.exception_handler(LLMProviderError)
def handle_llm_provider_error(
    request: Request, exc: LLMProviderError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"detail": "LLM provider returned an error"},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.exception_handler(BookNotFoundError)
@app.exception_handler(LibraryEntryNotFoundError)
@app.exception_handler(NoteNotFoundError)
def handle_not_found(
    request: Request,
    exc: BookNotFoundError | LibraryEntryNotFoundError | NoteNotFoundError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(NoteBookNotInLibraryError)
def handle_note_book_not_in_library(
    request: Request,
    exc: NoteBookNotInLibraryError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


@app.exception_handler(DuplicateLibraryEntryError)
def handle_conflict(request: Request, exc: DuplicateLibraryEntryError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )
