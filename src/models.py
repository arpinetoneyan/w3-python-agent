from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


QuestionType = Literal["choice", "fill", "drag"]


@dataclass
class Question:
    url: str
    heading: str
    prompt: str
    kind: QuestionType
    options: list[str] = field(default_factory=list)
    blank_count: int = 0


@dataclass
class Answer:
    kind: QuestionType
    choice_index: int | None = None
    blanks: list[str] = field(default_factory=list)
    drag_indices: list[int] = field(default_factory=list)
    explanation: str = ""


@dataclass
class QuestionResult:
    section: str
    url: str
    prompt: str
    answer: dict
    status: Literal["correct", "incorrect", "dry-run", "error"]
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
