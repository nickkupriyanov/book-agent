from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel


class ToolAccess(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    access: ToolAccess
    arguments_model: type[BaseModel]
    result_model: type[BaseModel]
