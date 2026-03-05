from dataclasses import dataclass, field
from typing import Optional

from loadforge.model.base import TxNode
from loadforge.model.values import ValueOrRef


@dataclass
class BodyField(TxNode):
    name: str = ""
    value: Optional["ValueOrRef"] = None


@dataclass
class BodyBlock(TxNode):
    fields: list[BodyField] = field(default_factory=list)


@dataclass
class AuthLogin(TxNode):
    file: Optional["ValueOrRef"] = None
    endpoint: Optional["ValueOrRef"] = None
    method: str = ""
    body: Optional[BodyBlock] = None
    format: str = ""
