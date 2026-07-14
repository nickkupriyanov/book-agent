from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import router
from app.exceptions import (
    BookNotFoundError,
    DuplicateLibraryEntryError,
    LibraryEntryNotFoundError,
)
from app.schemas import HealthResponse

app = FastAPI(title="Book Agent API", version="0.1.0")
app.include_router(router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.exception_handler(BookNotFoundError)
@app.exception_handler(LibraryEntryNotFoundError)
def handle_not_found(
    request: Request, exc: BookNotFoundError | LibraryEntryNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


@app.exception_handler(DuplicateLibraryEntryError)
def handle_conflict(request: Request, exc: DuplicateLibraryEntryError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )
