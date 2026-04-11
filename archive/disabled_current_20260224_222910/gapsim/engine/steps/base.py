from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from gapsim.engine.types import EngineState, RunContext

class Step(ABC):
    step_id: str

    @abstractmethod
    def apply(self, state: EngineState, ctx: RunContext, params: dict) -> EngineState:
        raise NotImplementedError
