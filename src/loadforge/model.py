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
class Test(TxNode):
    name: str = ""
    environment: Optional[Environment] = None
    target: Optional[Target] = None


@dataclass
class TestFile(TxNode):
    test: Optional[Test] = None
