from dataclasses import field, dataclass
from enum import Enum
from typing import Optional, Any

from loadforge.model.base import TxNode


class JsonCheckKind(Enum):
    isArray = "isArray"
    notEmpty = "notEmpty"
    equals = "equals"
    hasSize = "hasSize"


@dataclass
class Request(TxNode):
    method: str = ""  # GET/POST...
    path: str = ""    # STRING literal


@dataclass
class ExpectStatus(TxNode):
    code: int = 0


@dataclass
class ExpectJson(TxNode):
    path: str = ""
    check: "JsonCheck" = None


@dataclass
class JsonCheck(TxNode):
    kind: JsonCheckKind = None
    value: Optional[Any] = None
    size: Optional[int] = None


@dataclass
class Scenario(TxNode):
    name: str = ""
    steps: list[TxNode] = field(default_factory=list)  # Request | ExpectStatus
