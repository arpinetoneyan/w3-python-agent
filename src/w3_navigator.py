from __future__ import annotations

import re
from urllib.parse import urljoin

from playwright.sync_api import Page

from .models import Answer, Question


INDEX_URL = "https://www.w3schools.com/python/python_exercises.asp"
CAPTCHA_MARKERS = ("verify you are human", "captcha", "checking your browser")


class W3Navigator:
    def __init__(self, page: Page) -> None:
        self.page = page

    def resolve_sections(self, requested: list[str]) -> list[tuple[str, str]]:
        self.page.goto(INDEX_URL, wait_until="domcontentloaded", timeout=60_000)
        self._wait_ready()
        cards = self.page.locator('a[href*="exercise.asp?x=xrcise_"]')
        catalog: dict[str, tuple[str, str]] = {}
        for index in range(cards.count()):
            card = cards.nth(index)
            href = card.get_attribute("href")
            text = self._clean(card.inner_text())
            name = re.sub(r"\s+\d+\s+exercises.*$", "", text, flags=re.I).strip()
            if href and name:
                catalog[self._key(name)] = (name, urljoin(INDEX_URL, href))

        if not catalog:
            raise RuntimeError("No exercise sections found on the W3Schools index page")

        if any(self._key(item) == "all" for item in requested):
            return list(catalog.values())

        resolved: list[tuple[str, str]] = []
        missing: list[str] = []
        for item in requested:
            if item.startswith(("https://", "http://")):
                resolved.append((item, item))
            elif self._key(item) in catalog:
                resolved.append(catalog[self._key(item)])
            else:
                missing.append(item)
        if missing:
            sample = ", ".join(name for name, _ in list(catalog.values())[:12])
            raise ValueError(f"Unknown sections: {', '.join(missing)}. Examples: {sample}")
        return resolved

    def require_logged_in(self, timeout_ms: int = 15_000) -> None:
        """Wait until W3Schools switches the top navigation to account mode."""
        profile_button = self.page.locator("#tnb-user-profile")
        login_button = self.page.locator("#tnb-login-btn")
        checks = max(1, timeout_ms // 250)

        for _ in range(checks):
            profile_visible = bool(
                profile_button.count() and profile_button.first.is_visible()
            )
            login_visible = bool(login_button.count() and login_button.first.is_visible())
            if profile_visible and not login_visible:
                return
            self.page.wait_for_timeout(250)

        raise RuntimeError(
            "W3Schools login was not detected after 15 seconds. "
            "Make sure the account avatar is visible, then run: "
            "python -m src.main login"
        )

    def open_section(self, url: str, retake_completed: bool = False) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._wait_ready()
        if retake_completed:
            self._retake_if_needed()

    def read_question(self) -> Question | None:
        self._wait_for_answer_controls()
        self._guard_captcha()
        body = self.page.locator("body").inner_text(timeout=15_000)
        if self._is_finished(body):
            return None

        heading = self._first_text("h2", "Exercise")
        choice_inputs = self.page.locator('input[name="quizoption"]:visible')
        if choice_inputs.count():
            options = choice_inputs.evaluate_all(
                """els => els.map(el => {
                    const label = el.closest('label') || el.parentElement;
                    return (label?.innerText || el.value || '').trim();
                })"""
            )
            prompt = self._question_text(body, options)
            return Question(
                url=self.page.url,
                heading=heading,
                prompt=prompt,
                kind="choice",
                options=[self._clean(x) for x in options],
            )

        drag_options = self.page.locator(".dragoption")
        drop_boxes = self.page.locator(".ddcontainer:visible")
        if drag_options.count() and drop_boxes.count():
            options = drag_options.evaluate_all(
                "els => els.map(el => (el.innerText || el.textContent || '').trim())"
            )
            cleaned_options = [self._clean(x) for x in options]
            return Question(
                url=self.page.url,
                heading=heading,
                prompt=self._question_text(body, cleaned_options),
                kind="drag",
                options=cleaned_options,
                blank_count=drop_boxes.count(),
            )

        blanks = self.page.locator(
            'input:visible:not([type="radio"]):not([type="hidden"]):not([type="submit"])'
        )
        editable = self.page.locator('#assignmentcontainer[contenteditable="true"]:visible')
        if not blanks.count() and not editable.count():
            raise RuntimeError("No answer controls found; the W3Schools layout may have changed")
        return Question(
            url=self.page.url,
            heading=heading,
            prompt=self._question_text(body, []),
            kind="fill",
            blank_count=blanks.count() or 1,
        )

    def apply_answer(self, answer: Answer) -> None:
        if answer.kind == "choice":
            self.page.locator('input[name="quizoption"]:visible').nth(answer.choice_index).check()
        elif answer.kind == "drag":
            for index in answer.drag_indices:
                self.page.locator(".dragoption").nth(index).click()
                self.page.wait_for_timeout(150)
        else:
            blanks = self.page.locator(
                'input:visible:not([type="radio"]):not([type="hidden"]):not([type="submit"])'
            )
            if blanks.count():
                for index, value in enumerate(answer.blanks):
                    blanks.nth(index).fill(value)
            else:
                self.page.locator('#assignmentcontainer[contenteditable="true"]:visible').fill(
                    answer.blanks[0]
                )

    def submit(self) -> tuple[bool, str]:
        old_url = self.page.url
        button = self.page.get_by_role("button", name=re.compile("Submit Answer", re.I))
        button.click()
        self.page.wait_for_timeout(900)
        body = self.page.locator("body").inner_text()
        lowered = body.lower()
        if any(word in lowered for word in ("wrong", "incorrect", "not correct")):
            return False, self._result_message(body)
        if any(word in lowered for word in ("correct!", "correct answer", "well done")):
            if not self._is_finished(body):
                self._advance(old_url)
            return True, self._result_message(body)
        if self.page.url != old_url or self._is_finished(body):
            return True, "Advanced to the next exercise"
        return False, "The page did not confirm the answer"

    def _advance(self, old_url: str) -> None:
        candidates = self.page.get_by_role(
            "button", name=re.compile(r"Next|Continue|Exercise", re.I)
        )
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            label = candidate.inner_text().lower()
            if "submit" not in label and candidate.is_visible():
                candidate.click()
                self.page.wait_for_timeout(700)
                return
        submit = self.page.get_by_role("button", name=re.compile("Next", re.I))
        if submit.count():
            submit.first.click()
            self.page.wait_for_timeout(700)
        elif self.page.url == old_url:
            self.page.wait_for_timeout(500)

    def _wait_ready(self) -> None:
        self.page.wait_for_timeout(1200)
        self._guard_captcha()

    def _retake_if_needed(self) -> None:
        body = self.page.locator("body").inner_text(timeout=15_000).lower()
        if "already completed these exercises" not in body:
            return

        buttons = self.page.get_by_role("button", name=re.compile(r"^Yes$", re.I))
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.is_visible():
                button.click()
                self.page.wait_for_timeout(1000)
                return
        raise RuntimeError("The completed section could not be opened for a retake")

    def _wait_for_answer_controls(self, timeout_ms: int = 15_000) -> None:
        """Wait for exercises whose input fields are loaded asynchronously."""
        selectors = (
            'input[name="quizoption"]:visible',
            'input.editablesection:visible',
            '#assignmentcontainer[contenteditable="true"]:visible',
            '.dragoption:visible',
            '.ddcontainer:visible',
        )
        checks = max(1, timeout_ms // 250)
        for _ in range(checks):
            body = self.page.locator("body").inner_text(timeout=15_000)
            if self._is_finished(body):
                return
            if any(self.page.locator(selector).count() for selector in selectors):
                return
            self.page.wait_for_timeout(250)
        raise RuntimeError(
            "Answer controls did not load within 15 seconds; "
            "the W3Schools layout or connection may have changed"
        )

    def _guard_captcha(self) -> None:
        text = self.page.locator("body").inner_text(timeout=15_000).lower()
        if any(marker in text for marker in CAPTCHA_MARKERS):
            raise RuntimeError("CAPTCHA detected. Complete it manually and restart the agent.")

    @staticmethod
    def _is_finished(body: str) -> bool:
        lowered = body.lower()
        return any(
            marker in lowered
            for marker in (
                "completed all",
                "back to exercises",
                "you completed the",
                "already completed these exercises",
            )
        )

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _key(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    def _first_text(self, selector: str, fallback: str) -> str:
        locator = self.page.locator(selector)
        return self._clean(locator.first.inner_text()) if locator.count() else fallback

    def _question_text(self, body: str, options: list[str]) -> str:
        lines = [self._clean(line) for line in body.splitlines() if self._clean(line)]
        ignored = {
            "sign in", "show answer", "submit answer »", "what is an exercise?",
            "to track your progress",
        }
        result: list[str] = []
        for line in lines:
            low = line.lower()
            if low in ignored or line in options or line == "×" or low.startswith("exercise:"):
                continue
            if low.startswith(("test what you learned", "to try more python exercises")):
                break
            if len(result) < 14:
                result.append(line)
        return "\n".join(result)

    @staticmethod
    def _result_message(body: str) -> str:
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        matches = [
            line for line in lines
            if any(word in line.lower() for word in ("correct", "wrong", "well done"))
        ]
        return " | ".join(matches[:3]) or "Answer submitted"
