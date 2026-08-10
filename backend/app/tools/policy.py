from app.tools.models import ToolAccess


def requires_approval(access: ToolAccess) -> bool:
    return access is ToolAccess.DESTRUCTIVE
