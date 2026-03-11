from dataclasses import field, dataclass
from enum import Enum
from typing import Optional, Any

from loadforge.model.base import TxNode


class JsonCheckKind(Enum):
    isArray = "isArray"
    notEmpty = "notEmpty"
    equals = "equals"
    hasSize = "hasSize"
    isEmpty = "isEmpty"
    isNull = "isNull"
    notNull = "notNull"
    isObject = "isObject"
    isString = "isString"
    isNumber = "isNumber"
    isBool = "isBool"
    contains = "contains"
    matches = "matches"


class HttpMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass
class Request(TxNode):
    method: HttpMethod = HttpMethod.GET
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
