"""
setup.py — launcher запускаемый из run.bat / run.sh.

Зависимости УЖЕ установлены в venv через run.bat (там портативная установка
по принципу ComfyUI: всё в подпапке venv/, изолированно от системы).
Этот скрипт только:
  1. Проверяет что Ollama запущена и есть подходящие модели (warning, не fatal)
  2. Запускает uvicorn web:app

Если вы запускаете этот файл вручную (минуя run.bat), убедитесь что находитесь
в venv с уже установленными зависимостями.
"""

import os
import sys
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from ollama_utils import ensure_ollama_running, normalize_ollama_host, ollama_tags_url

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
DIM = "\033[2m"

OLLAMA_URL = normalize_ollama_host()
HF_CACHE_DIR = os.path.join(PROJECT_DIR, "models", "huggingface")
HF_TOKEN_KEYS = ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")


def info(msg):  print(f"{BLUE}[setup]{RESET} {msg}")
def ok(msg):    print(f"{GREEN}[ ok ]{RESET} {msg}")
def warn(msg):  print(f"{YELLOW}[warn]{RESET} {msg}")
def err(msg):   print(f"{RED}[err ]{RESET} {msg}")


def _read_hf_token_from_file(path):
    try:
        if not os.path.exists(path):
            return ""
        if path.endswith(".txt"):
            return open(path, "r", encoding="utf-8").read().strip()

        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip()
                if key in HF_TOKEN_KEYS:
                    return value.strip().strip('"').strip("'")
    except OSError as exc:
        warn(f"Could not read {os.path.basename(path)}: {exc}")
    return ""


def configure_huggingface():
    """Use a persistent local HF cache and optional token before models load."""
    os.makedirs(HF_CACHE_DIR, exist_ok=True)
    os.environ.setdefault("HF_HOME", HF_CACHE_DIR)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(HF_CACHE_DIR, "hub"))
    ok(f"Hugging Face cache: {os.path.relpath(HF_CACHE_DIR, PROJECT_DIR)}")

    token = next((os.environ.get(key, "").strip() for key in HF_TOKEN_KEYS if os.environ.get(key, "").strip()), "")
    if not token:
        for filename in ("huggingface_token.txt", ".env", ".env.local"):
            token = _read_hf_token_from_file(os.path.join(PROJECT_DIR, filename))
            if token:
                break

    if token:
        os.environ["HF_TOKEN"] = token
        os.environ["HUGGINGFACE_HUB_TOKEN"] = token
        ok("HF_TOKEN loaded for Hugging Face downloads")
    else:
        info("HF_TOKEN not set. Cached models load normally; first download may be rate-limited.")
        info("Optional: put HF_TOKEN=... in .env or paste the token in huggingface_token.txt")


def check_python():
    if sys.version_info < (3, 10):
        err(f"Python 3.10+ required, got {sys.version.split()[0]}")
        sys.exit(1)
    ok(f"Python {sys.version.split()[0]}")


def _has_nvidia_gpu() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_cuda_torch():
    """Replace CPU-only PyTorch with CUDA wheels when an NVIDIA GPU is present."""
    has_gpu = _has_nvidia_gpu()
    try:
        import torch
        version = getattr(torch, "__version__", "")
        cuda_build = getattr(torch.version, "cuda", None)
        cuda_available = bool(torch.cuda.is_available())
    except Exception as exc:
        warn(f"Could not inspect PyTorch: {exc}")
        return

    if not has_gpu:
        ok(f"PyTorch {version} ({'CUDA' if cuda_build else 'CPU'})")
        return

    if cuda_build and cuda_available:
        ok(f"PyTorch CUDA OK: {version}, CUDA {cuda_build}, {torch.cuda.get_device_name(0)}")
        return

    warn(f"NVIDIA GPU detected, but PyTorch is CPU-only or CUDA is unavailable: torch {version}, cuda={cuda_build}")
    info("Installing PyTorch CUDA 12.4 wheels into the portable Python. This can take several minutes.")
    cmd = [
        sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall",
        "torch==2.6.0+cu124",
        "torchvision==0.21.0+cu124",
        "--index-url", "https://download.pytorch.org/whl/cu124",
    ]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        warn(f"CUDA PyTorch install failed ({exc}). Backend will keep running, but Python models will use CPU.")
        warn("If this repeats, reinstall dependencies with run.bat or check antivirus/firewall access to download.pytorch.org.")
        return

    if os.environ.get("BTA_TORCH_CUDA_RESTARTED") != "1":
        info("Restarting launcher so Python reloads the CUDA PyTorch build...")
        os.environ["BTA_TORCH_CUDA_RESTARTED"] = "1"
        os.execv(sys.executable, [sys.executable] + sys.argv)
    warn("CUDA wheels were installed, but restart was already attempted. Continuing with current process.")


def check_ollama():
    """Проверяет что Ollama запущена и есть хотя бы одна мультимодальная модель."""
    info("Checking Ollama...")
    try:
        import requests
        ok_running, start_message = ensure_ollama_running(OLLAMA_URL, startup_timeout=20.0)
        if start_message:
            info(start_message)
        if not ok_running:
            raise RuntimeError(start_message)
        r = requests.get(ollama_tags_url(OLLAMA_URL), timeout=5)
        data = r.json()
    except Exception as e:
        warn(f"Ollama is not reachable at {OLLAMA_URL} ({e})")
        warn("Install from https://ollama.com or start it manually before translating.")
        warn("You can still launch the web UI to explore the interface.")
        return

    models = data.get("models", [])
    if not models:
        warn("Ollama is running but no models installed.")
        warn("Pull a multimodal model, for example:")
        print(f"   {DIM}ollama pull gemma3:4b{RESET}")
        print(f"   {DIM}ollama pull gemma3:12b{RESET}")
        print(f"   {DIM}ollama pull llava:13b{RESET}")
        warn("Also recommended for OCR:")
        print(f"   {DIM}ollama pull glm-ocr{RESET}")
        return

    # Простая эвристика: имена с известными vision-маркерами
    hints = ("vl", "vision", "llava", "gemma", "qwen", "minicpm",
             "llama4", "pixtral", "molmo", "phi")
    multimodal = [m["name"] for m in models
                   if any(h in m["name"].lower() for h in hints)
                   and "ocr" not in m["name"].lower()]

    if multimodal:
        ok(f"Ollama OK — multimodal models: {', '.join(multimodal[:5])}"
           + (f", +{len(multimodal)-5} more" if len(multimodal) > 5 else ""))
    else:
        warn(f"Ollama has {len(models)} model(s) but none look multimodal.")
        warn("Translation needs a vision-capable model. Try:")
        print(f"   {DIM}ollama pull gemma3:4b{RESET}")

    # OCR-модель
    has_ocr = any("ocr" in m["name"].lower() for m in models)
    if not has_ocr:
        warn("No OCR model detected (glm-ocr recommended). Pull with:")
        print(f"   {DIM}ollama pull glm-ocr{RESET}")


def launch_server():
    info("Starting web server...")
    print(f"{DIM}{'─' * 60}{RESET}")
    print(f"  Opening {GREEN}http://localhost:8000{RESET} in your browser...")
    print(f"  Press Ctrl+C to stop")
    print(f"{DIM}{'─' * 60}{RESET}")

    try:
        import uvicorn
    except ImportError:
        err("uvicorn not installed in this Python environment.")
        err("Run via run.bat (Windows) or run.sh (Linux/Mac) to set up venv automatically.")
        sys.exit(1)

    # КРИТИЧНО: embeddable Python не добавляет cwd в sys.path автоматически,
    # как делает обычный python. Без этого uvicorn.run("web:app", ...) падает
    # с "Could not import module 'web'". Добавляем директорию этого скрипта
    # в sys.path и меняем рабочую директорию на неё.
    script_dir = PROJECT_DIR
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    os.chdir(script_dir)

    # Открываем браузер из отдельного потока: дожидаемся пока порт начнёт
    # принимать соединения, потом запускаем системный браузер.
    # Если сделать это до uvicorn.run, страница покажет "сервер недоступен";
    # если использовать фиксированный sleep — на медленных машинах не хватит.
    import threading, socket, time, webbrowser

    def open_browser():
        url = "http://localhost:8000"
        # Ждём пока порт начнёт отвечать (макс. 30 секунд)
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            warn(f"Server didn't start listening in 30s — open {url} manually")
            return
        try:
            webbrowser.open(url)
        except Exception as e:
            warn(f"Couldn't open browser: {e}. Open {url} manually.")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        uvicorn.run("web:app", host="0.0.0.0", port=8000, log_level="info")
    except KeyboardInterrupt:
        print("\n" + DIM + "Server stopped." + RESET)


def _port_is_available(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _find_available_port(start: int, end: int = 8020) -> int | None:
    for port in range(start, end + 1):
        if _port_is_available(port):
            return port
    return None


def _is_existing_bta_server(port: int) -> bool:
    try:
        from urllib.request import urlopen

        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            body = response.read(4096).decode("utf-8", errors="ignore")
        return "BTA MangaTranslate" in body or "MangaTranslate" in body
    except Exception:
        return False


def _open_browser_when_ready(port: int):
    import socket
    import time
    import webbrowser

    url = f"http://localhost:{port}"
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.5)
    else:
        warn(f"Server did not start listening in 30s. Open {url} manually.")
        return

    try:
        webbrowser.open(url)
    except Exception as exc:
        warn(f"Could not open browser: {exc}. Open {url} manually.")


def launch_server():
    import threading
    import webbrowser

    requested_port = int(os.environ.get("BTA_PORT", "8000") or "8000")
    port = requested_port

    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    os.chdir(PROJECT_DIR)

    if not _port_is_available(port):
        if _is_existing_bta_server(port):
            url = f"http://localhost:{port}"
            ok(f"BTA MangaTranslate is already running on port {port}.")
            info(f"Opening existing server: {url}")
            try:
                webbrowser.open(url)
            except Exception as exc:
                warn(f"Could not open browser: {exc}. Open {url} manually.")
            return

        fallback_port = _find_available_port(port + 1)
        if fallback_port is None:
            err(f"Port {port} is busy and no free fallback port was found up to 8020.")
            err("Close the process using the port, or set BTA_PORT to a free port.")
            sys.exit(1)

        warn(f"Port {port} is already in use by another application.")
        warn(f"Starting backend on fallback port {fallback_port}.")
        warn("The Chrome extension expects port 8000 unless you update its SERVER constant.")
        port = fallback_port

    info("Starting web server...")
    print(f"{DIM}{'-' * 60}{RESET}")
    print(f"  Opening {GREEN}http://localhost:{port}{RESET} in your browser...")
    print("  Press Ctrl+C to stop")
    print(f"{DIM}{'-' * 60}{RESET}")

    try:
        import uvicorn
    except ImportError:
        err("uvicorn not installed in this Python environment.")
        err("Run via run.bat (Windows) or run.sh (Linux/Mac) to set up venv automatically.")
        sys.exit(1)

    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    try:
        uvicorn.run("web:app", host="0.0.0.0", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n" + DIM + "Server stopped." + RESET)


def main():
    print(f"\n{BLUE}═══ BTA MangaTranslate ═══{RESET}\n")
    check_python()
    configure_huggingface()
    ensure_cuda_torch()
    check_ollama()
    print()
    launch_server()


if __name__ == "__main__":
    main()
