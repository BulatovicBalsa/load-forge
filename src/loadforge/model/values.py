from dataclasses import dataclass, field
from typing import Optional

from loadforge.model.base import TxNode


@dataclass
class Ref(TxNode):
    name: str = ""


@dataclass
class ValueOrRef(TxNode):
    ref: Optional[Ref] = None
    value: str = ""


@dataclass
class VarEntry(TxNode):
    name: str = ""
    value: Optional[ValueOrRef] = None


@dataclass
class VariablesBlock(TxNode):
    vars: list[VarEntry] = field(default_factory=list)
