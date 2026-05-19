"""Small helpers for finding and starting the local Ollama server."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_OLLAMA_HOST = "http://localhost:11434"

_START_LOCK = threading.Lock()
_LAST_START_ATTEMPT = 0.0


def normalize_ollama_host(value: str | None = None) -> str:
    host = (value or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST).strip()
    if not host:
        host = DEFAULT_OLLAMA_HOST
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def ollama_tags_url(host: str | None = None) -> str:
    return f"{normalize_ollama_host(host)}/api/tags"


def ollama_generate_url(host: str | None = None) -> str:
    return f"{normalize_ollama_host(host)}/api/generate"


def is_local_ollama_host(host: str | None = None) -> bool:
    parsed = urlparse(normalize_ollama_host(host))
    return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def _ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found

    candidates = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
    if program_files:
        candidates.append(Path(program_files) / "Ollama" / "ollama.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Ollama" / "ollama.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def wait_for_ollama(host: str | None = None, timeout: float = 20.0, interval: float = 0.5) -> tuple[bool, str | None]:
    import requests

    url = ollama_tags_url(host)
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return True, None
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(interval)
    return False, last_error


def ensure_ollama_running(host: str | None = None, startup_timeout: float = 20.0) -> tuple[bool, str | None]:
    """Return (ok, message). Starts `ollama serve` for local hosts when needed."""
    global _LAST_START_ATTEMPT

    host = normalize_ollama_host(host)
    ok, error = wait_for_ollama(host, timeout=2.0, interval=0.25)
    if ok:
        return True, None

    if os.environ.get("BTA_OLLAMA_AUTOSTART", "1").strip().lower() in {"0", "false", "no", "off"}:
        return False, f"Ollama is not reachable at {ollama_tags_url(host)} ({error})"

    if not is_local_ollama_host(host):
        return False, f"Ollama is not reachable at remote host {ollama_tags_url(host)} ({error})"

    executable = _ollama_executable()
    if not executable:
        return False, "Ollama executable was not found. Install Ollama or add it to PATH."

    with _START_LOCK:
        ok, error = wait_for_ollama(host, timeout=1.0, interval=0.25)
        if ok:
            return True, None

        now = time.time()
        if now - _LAST_START_ATTEMPT < 5:
            return wait_for_ollama(host, timeout=startup_timeout, interval=0.5)
        _LAST_START_ATTEMPT = now

        env = os.environ.copy()
        env.setdefault("OLLAMA_NUM_PARALLEL", "2")
        env.setdefault("OLLAMA_CONTEXT_LENGTH", "4096")
        env.setdefault("OLLAMA_MAX_QUEUE", "256")
        parsed = urlparse(host)
        if parsed.netloc:
            env.setdefault("OLLAMA_HOST", parsed.netloc)

        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
        }
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True

        try:
            subprocess.Popen([executable, "serve"], **kwargs)
        except Exception as exc:
            return False, f"Could not start Ollama with '{executable} serve': {type(exc).__name__}: {exc}"

    ok, error = wait_for_ollama(host, timeout=startup_timeout, interval=0.5)
    if ok:
        return True, "Started Ollama automatically."
    return False, f"Started Ollama, but it did not answer at {ollama_tags_url(host)} ({error})"
