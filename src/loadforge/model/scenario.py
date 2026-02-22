from dataclasses import field, dataclass

from loadforge.model.base import TxNode


@dataclass
class Request(TxNode):
    method: str = ""  # GET/POST...
    path: str = ""    # STRING literal


@dataclass
class ExpectStatus(TxNode):
    code: int = 0


@dataclass
class Scenario(TxNode):
    name: str = ""
    steps: list[TxNode] = field(default_factory=list)  # Request | ExpectStatus
