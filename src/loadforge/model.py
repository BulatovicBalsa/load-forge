from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TxNode:
    parent: Optional[object] = field(default=None, repr=False)


@dataclass
class EnvCall(TxNode):
    key: str = ""  # STRING token, npr. "BASE_URL"


@dataclass
class EnvVar(TxNode):
    name: str = ""
    value: EnvCall = field(default_factory=EnvCall)


@dataclass
class Environment(TxNode):
    envVars: list[EnvVar] = field(default_factory=list)


@dataclass
class Ref(TxNode):
    name: str = ""


@dataclass
class Target(TxNode):
    ref: Optional[Ref] = None
    value: Optional[str] = None


@dataclass
class Duration(TxNode):
    hours: Optional[int] = None
    minutes: Optional[int] = None
    seconds: Optional[int] = None

    def total_seconds(self) -> int:
        return (self.hours or 0) * 3600 + (self.minutes or 0) * 60 + (self.seconds or 0)


@dataclass
class Load(TxNode):
    users: int = 0
    ramp_up: Duration = field(default_factory=Duration)
    duration: Duration = field(default_factory=Duration)


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



@dataclass
class Test(TxNode):
    name: str = ""
    environment: Optional[Environment] = None
    target: Optional[Target] = None
    load: Optional[Load] = None
    variables: Optional[VariablesBlock] = None
    scenarios: list[Scenario] = field(default_factory=list)


@dataclass
class TestFile(TxNode):
    test: Optional[Test] = None
