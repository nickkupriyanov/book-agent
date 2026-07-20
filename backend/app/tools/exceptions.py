from app.tools.models import ToolErrorCode


class ToolExecutionError(Exception):
    def __init__(self, code: ToolErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
