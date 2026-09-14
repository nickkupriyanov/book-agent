from app.demo import run_demo


def test_reproducible_http_demo() -> None:
    result = run_demo()

    assert result["read"] == {
        "status": "completed",
        "tools": ["get_user_library"],
    }
    assert result["multi_step_write"] == {
        "status": "completed",
        "tools": ["search_books", "add_book"],
    }
    assert result["approval"] == {
        "proposed_status": "waiting_for_approval",
        "completed_status": "completed",
        "book_count_before": 1,
        "book_count_after": 0,
    }
    assert [trace["tools"] for trace in result["safe_traces"]] == [
        ["get_user_library"],
        ["search_books", "add_book"],
        ["remove_book"],
    ]
