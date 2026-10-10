"""Browser tests: the real app, in a real (headless) browser.

These are OPTIONAL. They need Playwright and its browser:

    pip install -r requirements-dev.txt
    python -m playwright install chromium

Without them, every test in this folder is skipped with that explanation and
the rest of the suite still runs.

To watch a test happen:      python -m pytest tests/browser -q --headed-browser
To keep pictures of steps:   FOOTBALL_BROWSER_SHOTS=/some/folder python -m pytest tests/browser -q
"""
import os
from pathlib import Path

import pytest

from tests.live_server import LiveServer

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="Playwright is not installed (pip install -r requirements-dev.txt)",
)


@pytest.fixture(scope="session")
def browser(request):
    with sync_api.sync_playwright() as playwright:
        try:
            # Let a video start playing without a click, as a person at the keyboard could make it.
            launched = playwright.chromium.launch(
                headless=not request.config.getoption("--headed-browser"),
                args=["--autoplay-policy=no-user-gesture-required"],
            )
        except Exception as error:  # the browser itself is missing
            pytest.skip(f"Playwright's browser is not installed (python -m playwright install chromium): {error}")
        yield launched
        launched.close()


@pytest.fixture
def live_app(tmp_path):
    """The real server on its own port with its own empty data folder."""
    with LiveServer(tmp_path / "data") as server:
        yield server


@pytest.fixture
def page(browser, live_app, request):
    """A browser tab. The test fails if the page logs an error it did not expect."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    tab = context.new_page()
    tab.problems = []
    tab.expected_problems = []  # text fragments a test knows it will cause on purpose
    tab.on("pageerror", lambda error: tab.problems.append(f"uncaught error: {error}"))
    tab.on("console", lambda message: tab.problems.append(f"console {message.type}: {message.text}")
           if message.type == "error" else None)

    shots = os.environ.get("FOOTBALL_BROWSER_SHOTS")

    def snap(name: str) -> None:
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            tab.screenshot(path=str(Path(shots) / f"{request.node.name}-{name}.png"), full_page=True)

    tab.snap = snap
    yield tab
    unexpected = [problem for problem in tab.problems
                  if not any(fragment in problem for fragment in tab.expected_problems)]
    context.close()
    assert not unexpected, f"The page reported errors: {unexpected}"
