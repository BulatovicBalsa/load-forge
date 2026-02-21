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
class Test(TxNode):
    name: str = ""
    environment: Optional[Environment] = None
    target: Optional[Target] = None
    load: Optional[Load] = None


@dataclass
class TestFile(TxNode):
    test: Optional[Test] = None
