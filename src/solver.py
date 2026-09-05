from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from .models import Answer, Question


class ProgrammaticSolver:
    """Reads the answer data already loaded by the W3Schools exercise page."""

    def __init__(self, page: "Page") -> None:
        self.page = page

    def solve(self, question: Question, feedback: str = "") -> Answer:
        if question.kind == "choice":
            raw = self.page.evaluate(
                "() => (typeof qobj !== 'undefined' ? qobj.correct : null)"
            )
            if raw is None:
                raise RuntimeError("The page did not expose the correct option")
            index = int(raw)
            if not 0 <= index < len(question.options):
                raise RuntimeError(f"Invalid option index returned by the page: {index}")
            return Answer(
                kind="choice",
                choice_index=index,
                explanation="Correct option read from the exercise data",
            )

        if question.kind == "drag":
            raw = self.page.evaluate(
                "() => (typeof qobj !== 'undefined' ? qobj.correct : null)"
            )
            if not isinstance(raw, list):
                raise RuntimeError("The page did not expose the drag-and-drop answer")

            indices: list[int] = []
            used_indices: set[int] = set()
            for item in raw:
                # Some W3Schools questions allow more than one equivalent option.
                candidates = item if isinstance(item, list) else [item]
                if not candidates:
                    raise RuntimeError("The page returned an empty drag option list")
                candidate_indices = [int(value) for value in candidates]
                value = next(
                    (index for index in candidate_indices if index not in used_indices),
                    candidate_indices[0],
                )
                indices.append(value)
                used_indices.add(value)

            if len(indices) != question.blank_count:
                raise RuntimeError(
                    f"Expected {question.blank_count} drag answers, got {len(indices)}"
                )
            if any(index < 0 or index >= len(question.options) for index in indices):
                raise RuntimeError(f"Invalid drag option indices returned by the page: {indices}")
            return Answer(
                kind="drag",
                drag_indices=indices,
                explanation="Correct drag sequence read from the exercise data",
            )

        data = self.page.evaluate(
            """() => ({
                template: document.getElementById('assignmentcode')?.textContent || '',
                correct: document.getElementById('correctcode')?.textContent || '',
                editable: document.getElementById('assignmentcode')?.getAttribute('contenteditable') === 'true'
            })"""
        )
        template = str(data.get("template", ""))
        correct = str(data.get("correct", ""))
        if not correct:
            raise RuntimeError("The page did not expose the completed code")
        if data.get("editable"):
            return Answer(
                kind="fill",
                blanks=[correct],
                explanation="Completed code read from the exercise data",
            )

        blanks = self._extract_blanks(template, correct)
        if len(blanks) != question.blank_count:
            raise RuntimeError(
                f"Expected {question.blank_count} blanks, extracted {len(blanks)}"
            )
        return Answer(
            kind="fill",
            blanks=blanks,
            explanation="Missing fragments reconstructed from the exercise template",
        )

    @classmethod
    def _extract_blanks(cls, template: str, correct: str) -> list[str]:
        template = cls._normalize(template)
        correct = cls._normalize(correct)
        marker = re.compile(r"@(?:\(\d+\))?")
        parts = marker.split(template)
        marker_count = len(parts) - 1
        if marker_count < 1:
            raise RuntimeError("No blank markers found in the exercise template")

        pattern = "^"
        for index, part in enumerate(parts):
            pattern += cls._flexible_literal(part)
            if index < marker_count:
                pattern += "(.*?)"
        pattern += "$"
        match = re.match(pattern, correct, flags=re.S)
        if not match:
            raise RuntimeError("Could not align the incomplete and completed code")
        answers: list[str] = []
        for index, value in enumerate(match.groups()):
            # Every marker is rendered as a single-line HTML input. Flexible
            # matching can absorb adjacent blank lines, which must never be
            # entered into that input.
            value = value.strip("\r\n")
            # Preserve an answer made entirely of whitespace (Python
            # indentation). Also preserve leading indentation when the blank
            # starts at the beginning of a new source-code line.
            if value and value.isspace():
                answers.append(value)
            elif parts[index].endswith("\n"):
                answers.append(value.rstrip())
            else:
                answers.append(value.strip())
        return answers

    @staticmethod
    def _normalize(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").strip()

    @staticmethod
    def _flexible_literal(value: str) -> str:
        chunks = re.split(r"(\s+)", value)
        # Keep whitespace matching flexible, but non-greedy: otherwise a newline
        # immediately before a blank can consume the indentation that is the answer.
        return "".join(r"\s+?" if chunk.isspace() else re.escape(chunk) for chunk in chunks)
