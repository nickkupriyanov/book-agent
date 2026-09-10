from app.catalog.models import CatalogSource
from app.schemas import AgentStepResponse


def test_agent_step_exposes_only_safe_catalog_search_metadata() -> None:
    step = AgentStepResponse(
        step_number=1,
        messages=[{"content": "secret prompt"}],
        response={"tool_calls": [{"name": "search_books"}]},
        tool_results=[
            {
                "tool_name": "search_books",
                "output": {
                    "source": "open_library",
                    "degraded": False,
                    "cached": True,
                    "books": [{"title": "secret raw book"}],
                    "provider_payload": "secret payload",
                },
                "error": None,
            },
            {
                "tool_name": "add_book",
                "output": {
                    "source": "local",
                    "degraded": False,
                    "cached": False,
                },
            },
            {
                "tool_name": "search_books",
                "output": {
                    "source": "unknown_provider",
                    "degraded": "false",
                    "cached": False,
                },
            },
        ],
        error=None,
        duration_ms=12,
    )

    assert [
        search.model_dump() for search in step.catalog_searches
    ] == [
        {
            "source": CatalogSource.OPEN_LIBRARY,
            "degraded": False,
            "cached": True,
        }
    ]
    assert step.model_dump(mode="json")["catalog_searches"] == [
        {
            "source": "open_library",
            "degraded": False,
            "cached": True,
        }
    ]


def test_agent_step_keeps_old_trace_without_catalog_metadata_compatible() -> None:
    step = AgentStepResponse(
        step_number=1,
        messages=[],
        response=None,
        tool_results=[],
        error=None,
        duration_ms=1,
    )

    assert step.catalog_searches == []
