"""Starts the REAL server as a separate process, for tests that need the whole app
(the restart test and the browser tests). Each server gets its own data folder,
so these tests can never touch your real data.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LiveServer:
    def __init__(self, data_dir: Path, port: int | None = None):
        self.data_dir = Path(data_dir)
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen | None = None

    def request(self, method: str, path: str, body: dict | None = None):
        """Call the API and return the parsed JSON answer (None for an empty answer)."""
        request = urllib.request.Request(
            self.url + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def start(self) -> "LiveServer":
        env = {**os.environ, "FOOTBALL_DATA_DIR": str(self.data_dir), "ALLOWED_HOSTS": "127.0.0.1",
               "FOOTBALL_IGNORE_DOTENV": "1"}
        for name in ("AI_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "AI_MODEL"):
            env.pop(name, None)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--port", str(self.port), "--log-level", "warning"],
            cwd=BACKEND_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if self.request("GET", "/api/health")["status"] == "ok":
                    return self
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        self.stop()
        raise AssertionError("The server did not start within 20 seconds")

    def stop(self) -> None:
        if self.process is not None:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None

    def __enter__(self) -> "LiveServer":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()
