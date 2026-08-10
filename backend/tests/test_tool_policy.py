import pytest

from app.tools.models import ToolAccess
from app.tools.policy import requires_approval


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        (ToolAccess.READ, False),
        (ToolAccess.WRITE, False),
        (ToolAccess.DESTRUCTIVE, True),
    ],
)
def test_requires_approval_policy(access: ToolAccess, expected: bool) -> None:
    assert requires_approval(access) is expected
