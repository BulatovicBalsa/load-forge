from dataclasses import dataclass, field

from loadforge.model.base import TxNode


@dataclass
class MetricExpectation(TxNode):
    metric: str = ""   # p50 | p95 | p99 | avg | min | max | errorRate
    op: str = ""       # < | <= | > | >=
    value: str = ""    # numeric literal from grammar (stored as string)
    unit: str = ""     # ms | %


@dataclass
class MetricsBlock(TxNode):
    checks: list[MetricExpectation] = field(default_factory=list)
