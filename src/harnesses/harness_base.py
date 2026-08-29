from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from langchain_core.messages import BaseMessage
from src.task_base import TaskInstance


@dataclass
class HarnessOutput:
    messages: list[BaseMessage]
    metadata: dict


class HarnessBase(ABC):

    name: str = ""

    @abstractmethod
    def build_messages(self, instance: TaskInstance) -> HarnessOutput: ...