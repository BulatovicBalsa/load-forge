from dataclasses import dataclass, field
from typing import Optional

from loadforge.model.base import TxNode
from loadforge.model.load import Load
from loadforge.model.scenario import Scenario
from loadforge.model.values import VariablesBlock, Ref


@dataclass
class EnvCall(TxNode):
    key: str = ""


@dataclass
class EnvVar(TxNode):
    name: str = ""
    value: EnvCall = field(default_factory=EnvCall)


@dataclass
class Environment(TxNode):
    envVars: list[EnvVar] = field(default_factory=list)


@dataclass
class Target(TxNode):
    ref: Optional[Ref] = None
    value: Optional[str] = None


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