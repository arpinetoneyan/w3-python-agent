from __future__ import annotations

import argparse
import re
from dataclasses import asdict
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from .models import QuestionResult
from .reporter import RunReporter
from .solver import ProgrammaticSolver
from .w3_navigator import INDEX_URL, W3Navigator


ROOT = Path(__file__).resolve().parents[1]


def save_completion_screenshot(page, section_name: str, started_at) -> Path:
    screenshot_dir = ROOT / "reports" / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", section_name).strip("_") or "section"
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    path = screenshot_dir / f"{timestamp}_{safe_name}_completed.png"
    # Give W3Schools time to persist the final result before taking evidence.
    page.wait_for_timeout(1500)
    page.screenshot(path=str(path), full_page=False)
    return path


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not config.get("sections"):
        raise ValueError("Add at least one section to config.yaml")
    return config


def login(config: dict) -> None:
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(ROOT / "browser-data"),
            headless=False,
            slow_mo=config.get("slow_mo_ms", 250),
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(INDEX_URL, wait_until="domcontentloaded", timeout=60_000)
        print("Log in to W3Schools in the opened browser window.")
        input("After login is complete, press Enter here...")
        page.goto(INDEX_URL, wait_until="domcontentloaded", timeout=60_000)
        navigator = W3Navigator(page)
        navigator.require_logged_in()
        print("Login verified and saved.")
        context.close()


def run(config: dict, dry_run: bool, retake_completed: bool = False) -> None:
    reporter = RunReporter()
    max_attempts = int(config.get("max_attempts_per_question", 2))

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(ROOT / "browser-data"),
            headless=bool(config.get("headless", False)),
            slow_mo=int(config.get("slow_mo_ms", 250)),
        )
        page = context.pages[0] if context.pages else context.new_page()
        navigator = W3Navigator(page)
        solver = ProgrammaticSolver(page)
        sections = navigator.resolve_sections(config["sections"])
        navigator.require_logged_in()
        print("W3Schools account login verified")

        for section_name, section_url in sections:
            print(f"\n=== {section_name} ===")
            navigator.open_section(section_url, retake_completed=retake_completed)
            seen_urls: dict[str, int] = {}

            while True:
                question = navigator.read_question()
                if question is None:
                    print("Section completed")
                    screenshot_path = save_completion_screenshot(
                        page, section_name, reporter.started_at
                    )
                    print(f"Completion screenshot saved to: {screenshot_path}")
                    break
                seen_urls[question.url] = seen_urls.get(question.url, 0) + 1
                if seen_urls[question.url] > max_attempts + 2:
                    raise RuntimeError(f"Agent is stuck on {question.url}")

                feedback = ""
                final_status = "error"
                final_details = ""
                answer = None
                for attempt in range(1, max_attempts + 1):
                    answer = solver.solve(question, feedback)
                    print(f"Question: {question.prompt[:100]}")
                    print(f"Decision: {answer.explanation}")
                    if dry_run:
                        final_status = "dry-run"
                        final_details = "Answer was generated but not submitted"
                        break
                    navigator.apply_answer(answer)
                    correct, feedback = navigator.submit()
                    final_details = feedback
                    if correct:
                        final_status = "correct"
                        break
                    final_status = "incorrect"
                    print(f"Attempt {attempt} failed: {feedback}")

                reporter.add(
                    QuestionResult(
                        section=section_name,
                        url=question.url,
                        prompt=question.prompt,
                        answer=asdict(answer) if answer else {},
                        status=final_status,
                        details=final_details,
                    )
                )
                if dry_run:
                    break
                if final_status != "correct":
                    raise RuntimeError(f"Could not solve question: {question.url}")

        context.close()

    report_path = reporter.save(ROOT / "reports")
    print(f"\nReport saved to: {report_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="W3Schools Python exercise agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("login", help="Open the browser and save a local login session")
    run_parser = subparsers.add_parser("run", help="Solve configured exercise sections")
    run_parser.add_argument("--dry-run", action="store_true", help="Generate but do not submit")
    run_parser.add_argument(
        "--retake-completed",
        action="store_true",
        help="Retake locally completed sections so progress is saved to the account",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config()
    if args.command == "login":
        login(config)
    else:
        run(config, args.dry_run, args.retake_completed)


if __name__ == "__main__":
    main()
