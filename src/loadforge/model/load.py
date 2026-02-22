from dataclasses import dataclass, field
from typing import Optional

from loadforge.model.base import TxNode


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