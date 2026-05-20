"""
web.py
Веб-интерфейс для manga_translator.py

Запуск:
    uvicorn web:app --host 0.0.0.0 --port 8000

Откройте http://localhost:8000 в браузере.
"""

import os
import sys
import json
import shutil
import asyncio
import tempfile
import uuid
import re
import hashlib
import unicodedata
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from collections import Counter
from pathlib import Path
from typing import Optional

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

import manga_translator as mt
from ollama_utils import ensure_ollama_running, normalize_ollama_host, ollama_tags_url


# ─── состояние и пути ─────────────────────────────────────────────────────────

BASE_DIR = Path("web_data")
UPLOADS_DIR = BASE_DIR / "uploads"
RESULTS_DIR = BASE_DIR / "results"
JOBS_DIR = BASE_DIR / "jobs"          # bubbles.json по каждому job_id
ICONS_DIR = Path(__file__).parent / "chrome_extension" / "icons"
FAVICON_PATH = ICONS_DIR / "favicon.ico"

for d in (UPLOADS_DIR, RESULTS_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Активные джобы: job_id → {"status", "pages", "stats", "ws_queue"}
JOBS: dict = {}
LIVE_TRANSLATION_CACHE: dict[tuple[str, ...], str] = {}
LIVE_OCR_CACHE: dict[tuple[str, int, int, int, int], str] = {}
LIVE_DETECTION_CACHE: dict[str, list[dict]] = {}
LIVE_IMAGE_RESULT_CACHE: dict[tuple[str, ...], dict] = {}
WEB_OCR_CONCURRENCY = max(1, int(os.environ.get("BTA_WEB_OCR_CONCURRENCY", "5") or "5"))
WEB_TRANSLATION_BATCH_SIZE = max(1, int(os.environ.get("BTA_WEB_TRANSLATION_BATCH", "5") or "5"))
WEB_TRANSLATION_CONCURRENCY = max(1, int(os.environ.get("BTA_WEB_TRANSLATION_CONCURRENCY", "2") or "2"))
WEB_LLM_CONCURRENCY = max(1, int(os.environ.get("BTA_WEB_LLM_CONCURRENCY", "2") or "2"))
WEB_CACHE_LIMIT = max(20, int(os.environ.get("BTA_WEB_CACHE_LIMIT", "240") or "240"))
WEB_SPLIT_TEXT_GROUPS = os.environ.get("BTA_WEB_SPLIT_TEXT_GROUPS", "1").strip().lower() in ("1", "true", "yes", "on")
WEB_SPLIT_VISUAL_TEXT = os.environ.get("BTA_WEB_SPLIT_VISUAL_TEXT", "1").strip().lower() in ("1", "true", "yes", "on")
WEB_FALLBACK_TEXT_REGIONS = os.environ.get("BTA_WEB_FALLBACK_TEXT_REGIONS", "0").strip().lower() in ("1", "true", "yes", "on")
WEB_DETECTION_THRESHOLD = max(0.2, min(0.8, float(os.environ.get("BTA_WEB_DETECTION_THRESHOLD", "0.38") or "0.38")))
LIVE_LLM_SEMAPHORE = asyncio.Semaphore(WEB_LLM_CONCURRENCY)

PROMPT_ECHO_BLOCKED_FRAGMENTS = (
    "please provide",
    "provide the ocr",
    "ocr text",
    "actual text",
    "i need the",
    "cannot translate",
    "can't translate",
    "unable to translate",
    "i'm sorry",
    "as an ai",
    "no text",
    "no translation",
    "manga bubble",
    "bubble image",
    "words printed",
    "visible line",
    "visible lines",
    "visible text",
    "return only",
    "transcribe only",
    "read any visible",
    "read only",
    "keep visible",
    "keep the visible",
    "keeping the original",
    "preserve line",
    "paragraph breaks",
    "no explanation",
    "leia apenas",
    "apenas o texto",
    "texto impresso",
    "texto visivel",
    "retorne apenas",
    "sem explicacao",
    "nao ha texto",
    "nao consigo",
    "mantenha as quebras",
    "linhas visiveis",
    "se nao houver texto",
)

VISUAL_FAILURE_BLOCKED_FRAGMENTS = (
    "image is too blurry",
    "image is blurry",
    "too blurry",
    "pixelated",
    "cannot read the image",
    "can't read the image",
    "cant read the image",
    "cannot read this image",
    "no readable text",
    "unreadable text",
    "a imagem esta",
    "imagem esta muito",
    "imagem muito",
    "muito borrada",
    "com pixels",
    "pixelizada",
    "nao consigo ler",
    "nao da para ler",
    "texto ilegivel",
    "nao ha texto legivel",
)


def _safe_slug(value: str, fallback: str = "untitled") -> str:
    value = (value or "").strip()
    value = re.sub(r"[^\w\-. ]+", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value).strip("._-")
    return value[:80] or fallback


def _job_storage_name(job_id: str, config: dict | None = None) -> str:
    config = config or {}
    work = _safe_slug(config.get("work_title") or "", "")
    chapter = _safe_slug(config.get("chapter_number") or "", "")
    lang = _safe_slug(config.get("target_lang_code") or config.get("target_lang") or "", "")
    parts = [part for part in (work, f"chapter_{chapter}" if chapter else "", lang, job_id) if part]
    return "__".join(parts) if parts else job_id


def _job_meta_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}_meta.json"


def _write_job_meta(job_id: str, job: dict):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "job_id": job_id,
        "status": job.get("status", "ready"),
        "completed": job.get("completed", 0),
        "total_pages": job.get("total_pages", 0),
        "storage_name": job.get("storage_name", job_id),
        "config": job.get("config", {}),
    }
    _job_meta_path(job_id).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _image_ext_from_content_type(content_type: str | None) -> str:
    ext_by_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return ext_by_type.get((content_type or "").split(";")[0].lower(), "")


def _safe_upload_filename(filename: str | None, index: int, content_type: str | None = None) -> str | None:
    name = Path(filename or "").name
    stem = Path(name).stem or f"page_{index:03d}"
    ext = Path(name).suffix.lower()
    if ext not in mt.SUPPORTED_EXTENSIONS:
        ext = _image_ext_from_content_type(content_type)
    if ext not in mt.SUPPORTED_EXTENSIONS:
        return None
    return f"{index:03d}_{_safe_slug(stem, f'page_{index:03d}')}{ext}"


def _read_job_meta(job_id: str) -> dict:
    path = _job_meta_path(job_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"job_id": job_id, "storage_name": job_id, "config": {}}


def _job_original_pages(job_id: str) -> list[dict]:
    meta = _read_job_meta(job_id)
    storage_name = meta.get("storage_name", job_id)
    upload_dir = UPLOADS_DIR / storage_name
    if not upload_dir.exists():
        legacy_upload_dir = UPLOADS_DIR / job_id
        upload_dir = legacy_upload_dir if legacy_upload_dir.exists() else upload_dir
        storage_name = job_id if upload_dir == legacy_upload_dir else storage_name

    pages = []
    if not upload_dir.exists():
        return pages

    files = [
        path for path in upload_dir.iterdir()
        if path.is_file() and path.suffix.lower() in mt.SUPPORTED_EXTENSIONS
    ]
    for idx, path in enumerate(sorted(files, key=lambda p: mt.natural_key(p.name)), start=1):
        width = height = 0
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            pass
        pages.append({
            "page": idx,
            "filename": path.name,
            "url": f"/files/uploads/{storage_name}/{path.name}",
            "source_url": f"/files/uploads/{storage_name}/{path.name}",
            "image_width": width,
            "image_height": height,
            "bubbles": [],
            "elapsed": 0,
            "translated": False,
        })
    return pages


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="BTA MangaTranslate")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Раздаём результаты статикой — браузер сможет тянуть картинки напрямую
app.mount("/files", StaticFiles(directory=BASE_DIR), name="files")


@app.on_event("startup")
async def preload_inpainting_model():
    """Preload anime-big-lama during backend startup so full renders are ready."""
    ok, message = await asyncio.to_thread(ensure_ollama_running, OLLAMA_HOST, 20.0)
    if ok:
        print(f"[startup] Ollama ready at {OLLAMA_HOST}" + (f" ({message})" if message else ""))
    else:
        print(f"[startup] Ollama unavailable at {OLLAMA_HOST}: {message}")

    print("[startup] Preloading anime-big-lama inpainting model...")
    model = await asyncio.to_thread(mt.get_inpainting_model)
    if model is None:
        print("[startup] anime-big-lama unavailable or disabled; using cv2.inpaint fallback")
    else:
        print("[startup] anime-big-lama ready")


# ─── главная страница ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((Path(__file__).parent / "web_ui.html").read_text(encoding="utf-8"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if FAVICON_PATH.exists():
        return FileResponse(FAVICON_PATH)
    raise HTTPException(404, "favicon not found")


# ─── список доступных LLM-моделей из Ollama ──────────────────────────────────

# URL Ollama можно переопределить переменной окружения OLLAMA_HOST
# (Ollama использует ту же переменную). По умолчанию — localhost:11434.
OLLAMA_HOST = normalize_ollama_host()


def _fetch_ollama_models() -> tuple[list, str | None]:
    """
    Запрашивает /api/tags у Ollama и возвращает (список_моделей, ошибка_или_None).
    Если что-то пошло не так — пишет в консоль развёрнутую диагностику.
    """
    import requests as _req
    ok, start_message = ensure_ollama_running(OLLAMA_HOST, startup_timeout=15.0)
    if start_message:
        print(f"[/api/models] {start_message}")
    if not ok:
        msg = (f"Cannot connect to Ollama at {ollama_tags_url(OLLAMA_HOST)}. "
               f"{start_message}")
        print(f"[/api/models] {msg}")
        return [], msg

    url = ollama_tags_url(OLLAMA_HOST)
    try:
        r = _req.get(url, timeout=5)
    except _req.exceptions.ConnectionError as e:
        msg = (f"Cannot connect to Ollama at {url}. "
               "Make sure Ollama is running (try 'ollama list' in terminal). "
               f"Details: {e}")
        print(f"[/api/models] {msg}")
        return [], msg
    except Exception as e:
        msg = f"Unexpected error reaching {url}: {type(e).__name__}: {e}"
        print(f"[/api/models] {msg}")
        return [], msg

    if r.status_code != 200:
        msg = f"Ollama returned HTTP {r.status_code} from {url}: {r.text[:200]}"
        print(f"[/api/models] {msg}")
        return [], msg

    try:
        data = r.json()
    except Exception as e:
        msg = f"Ollama response is not valid JSON: {e}; body: {r.text[:200]}"
        print(f"[/api/models] {msg}")
        return [], msg

    models = data.get("models", [])
    print(f"[/api/models] Ollama at {url}: {len(models)} model(s) installed")
    return models, None


# Имена которые ТОЧНО мультимодальные — фильтр должен пропускать их без вопросов
KNOWN_MULTIMODAL = (
    "llava", "bakllava", "moondream", "minicpm-v", "minicpm",
    "qwen2-vl", "qwen2.5-vl", "qwen-vl",
    "llama3.2-vision", "llama4",
    "pixtral", "molmo",
    "gemma3", "gemma4",  # обе поддерживают vision
    "phi3.5-vision", "phi-3-vision", "phi3-vision", "phi4-vision",
    "internvl", "cogvlm", "yi-vl",
)
# Семейства из ollama show — означают что у модели есть vision-проектор
MULTIMODAL_FAMILIES = {"clip", "mllama", "llava", "gemma3", "gemma4"}
# OCR-модели не подходят для перевода/анализа сцены, прячем их
OCR_FAMILIES = {"glmocr"}
OCR_NAME_HINTS = ("glm-ocr", "tesseract", "paddleocr", "easyocr")
# Не-мультимодальные модели которые могут случайно матчиться по подстроке "gemma" или "phi"
NEVER_MULTIMODAL = ("gemma:", "gemma2:", "gemma2-", "phi3:", "phi3-mini", "phi:")


def _is_ocr(name: str, family: str, families: set) -> bool:
    """OCR-модели исключаем из списка LLM."""
    name_lower = name.lower()
    if any(hint in name_lower for hint in OCR_NAME_HINTS):
        return True
    if family.lower() in OCR_FAMILIES:
        return True
    if families & OCR_FAMILIES:
        return True
    return False


def _is_multimodal(name: str, family: str, families: set) -> bool:
    """Решает мультимодальная модель или нет, на основе имени + метаданных Ollama."""
    name_lower = name.lower()
    # Жёсткое исключение
    if any(name_lower.startswith(p) for p in NEVER_MULTIMODAL):
        return False
    # Жёсткое включение по имени (subscring match, чтобы ловить
    # huihui_ai/gemma-4-abliterated:26b, ollama пользовательских сборок и т.п.)
    if any(known in name_lower for known in KNOWN_MULTIMODAL):
        return True
    # gemma-4 как имя файла без 'gemma4' — например 'gemma-4-abliterated'
    if "gemma-4" in name_lower or "gemma-3" in name_lower:
        return True
    # Метаданные Ollama: family/families указывают на vision
    if family.lower() in MULTIMODAL_FAMILIES:
        return True
    if families & MULTIMODAL_FAMILIES:
        return True
    return False


@app.get("/api/models")
async def list_models():
    """Список Ollama-моделей с пометкой какие мультимодальные / OCR."""
    models_raw, error = _fetch_ollama_models()
    out = []
    for m in models_raw:
        name = m.get("name", "")
        details = m.get("details") or {}
        families = set(f.lower() for f in (details.get("families") or []))
        family = (details.get("family") or "")
        size_bytes = m.get("size", 0)

        ocr = _is_ocr(name, family, families)
        is_multi = _is_multimodal(name, family, families) if not ocr else False

        out.append({
            "name": name,
            "size_gb": round(size_bytes / (1024 ** 3), 1),
            "family": family,
            "families": sorted(families),
            "multimodal": is_multi,
            "ocr": ocr,
        })
    # Multimodal first, then "other" LLMs, OCR last
    out.sort(key=lambda m: (m["ocr"], not m["multimodal"], m["name"]))
    return {
        "models": out,
        "default": mt.LLM_MODEL,
        "ollama_host": OLLAMA_HOST,
        "error": error,
    }


@app.get("/api/models/debug")
async def debug_models():
    """
    Возвращает СЫРОЙ ответ Ollama для диагностики.
    Открой http://localhost:8000/api/models/debug в браузере чтобы посмотреть.
    """
    import requests as _req
    ok, start_message = ensure_ollama_running(OLLAMA_HOST, startup_timeout=15.0)
    url = ollama_tags_url(OLLAMA_HOST)
    if not ok:
        return {
            "ollama_host": OLLAMA_HOST,
            "url_queried": url,
            "error": start_message,
        }
    try:
        r = _req.get(url, timeout=5)
        return {
            "ollama_host": OLLAMA_HOST,
            "url_queried": url,
            "http_status": r.status_code,
            "raw_response": r.json() if r.status_code == 200 else r.text,
        }
    except Exception as e:
        return {
            "ollama_host": OLLAMA_HOST,
            "url_queried": url,
            "error": f"{type(e).__name__}: {e}",
        }


# ─── загрузка главы ──────────────────────────────────────────────────────────

def _font_label(path: Path) -> str:
    label = path.stem.replace("_", " ").replace("-", " ")
    for token in ("Regular", "Normal", "Roman"):
        label = label.replace(token, "").strip()
    return re.sub(r"\s+", " ", label) or path.name


def _installed_font_dirs() -> list[Path]:
    dirs = [
        Path(__file__).parent / "fonts",
        Path.cwd() / "fonts",
    ]
    if os.name == "nt":
        windir = os.environ.get("WINDIR", "C:/Windows")
        local = os.environ.get("LOCALAPPDATA", "")
        dirs.append(Path(windir) / "Fonts")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        dirs.extend([
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
            Path("/Library/Fonts"),
            Path("/System/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ])
    return dirs


@app.get("/api/fonts")
async def list_fonts():
    """Return fonts installed on the backend device plus local project fonts."""
    exts = {".ttf", ".otf", ".ttc"}
    seen = set()
    fonts = [{
        "label": "Comic Bold",
        "path": mt.DEFAULT_FONT_ALIAS,
        "file": mt.DEFAULT_FONT_ALIAS,
        "bold": True,
        "local": True,
        "virtual": True,
    }]
    project_root = str(Path(__file__).parent).lower()

    for folder in _installed_font_dirs():
        if not folder.exists():
            continue
        try:
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in exts:
                    continue
                resolved = str(path.resolve())
                key = resolved.lower()
                if key in seen:
                    continue
                seen.add(key)
                file_lower = path.name.lower()
                fonts.append({
                    "label": _font_label(path),
                    "path": resolved,
                    "file": path.name,
                    "bold": any(word in file_lower for word in ("bold", "black", "heavy", "bd", "semibold")),
                    "local": key.startswith(project_root),
                })
        except OSError:
            continue

    preferred = ("comicbd.ttf", "comic sans ms bold.ttf", "arialbd.ttf", "arial.ttf", "calibrib.ttf", "verdanab.ttf", "dejavusans-bold.ttf")
    fonts.sort(key=lambda f: (
        0 if f.get("path") == mt.DEFAULT_FONT_ALIAS else 1,
        preferred.index(f["file"].lower()) if f["file"].lower() in preferred else len(preferred),
        not f["local"],
        not f["bold"],
        f["label"].lower(),
        f["file"].lower(),
    ))
    return {
        "fonts": fonts,
        "default": mt.DEFAULT_FONT_ALIAS,
    }


@app.post("/api/fetch-image")
async def fetch_remote_image(payload: dict):
    url = str(payload.get("url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Invalid image URL")

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 BTA-MangaTranslate/1.0",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            data = response.read(30 * 1024 * 1024 + 1)
    except Exception as exc:
        raise HTTPException(400, f"Could not fetch image: {exc}")

    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "Image is larger than 30 MB")

    ext = _image_ext_from_content_type(content_type) or Path(parsed.path).suffix.lower()
    if ext not in mt.SUPPORTED_EXTENSIONS:
        raise HTTPException(415, "URL does not point to a supported image")

    media_type = content_type if content_type.startswith("image/") else "application/octet-stream"
    return Response(
        content=data,
        media_type=media_type,
        headers={"X-BTA-Filename": f"web_image{ext}"},
    )


class _ChapterImageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.urls: list[str] = []
        self._seen: set[str] = set()
        self.title = ""
        self._in_title = False

    def _add(self, value: str):
        value = (value or "").strip()
        if not value or value.startswith(("data:", "blob:", "#")):
            return
        url = urllib.parse.urljoin(self.base_url, value)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return
        normalized = urllib.parse.urldefrag(url)[0]
        lower = normalized.lower()
        skip_tokens = ("avatar", "banner", "logo", "icon", "sprite", "ads", "advert", "tracking", "pixel")
        if any(token in lower for token in skip_tokens):
            return
        if normalized not in self._seen:
            self._seen.add(normalized)
            self.urls.append(normalized)

    def _add_srcset(self, value: str):
        for part in (value or "").split(","):
            candidate = part.strip().split()
            if candidate:
                self._add(candidate[0])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in ("img", "source"):
            for key in ("src", "data-src", "data-original", "data-lazy-src", "data-url", "data-full"):
                self._add(attrs_map.get(key, ""))
            for key in ("srcset", "data-srcset"):
                self._add_srcset(attrs_map.get(key, ""))
        if tag.lower() == "meta":
            prop = (attrs_map.get("property") or attrs_map.get("name") or "").lower()
            if prop in ("og:image", "twitter:image"):
                self._add(attrs_map.get("content", ""))

    def handle_endtag(self, tag: str):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str):
        if self._in_title:
            self.title = (self.title + " " + data.strip()).strip()


@app.post("/api/chapter-images")
async def chapter_images(payload: dict):
    url = str(payload.get("url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "Invalid chapter URL")

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 BTA-MangaTranslate/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw = response.read(5 * 1024 * 1024)
    except Exception as exc:
        raise HTTPException(400, f"Could not fetch chapter: {exc}")

    if "html" not in content_type and "xml" not in content_type and b"<html" not in raw[:4096].lower():
        raise HTTPException(415, "URL does not look like a chapter HTML page")

    parser = _ChapterImageParser(url)
    parser.feed(raw.decode("utf-8", errors="ignore"))
    images = parser.urls[:250]
    if not images:
        raise HTTPException(404, "No chapter images found")
    return {"url": url, "title": parser.title, "count": len(images), "images": images}


@app.post("/api/upload")
async def upload_chapter(
    files: list[UploadFile] = File(...),
    source_lang: str = Form("Auto"),
    target_lang: str = Form("Russian"),
    font_path: str = Form(mt.DEFAULT_FONT_ALIAS),
    debug: bool = Form(False),
    llm_model: str = Form(""),
    llm_debug: bool = Form(False),
    fast_mode: bool = Form(False),
    work_title: str = Form(""),
    chapter_number: str = Form(""),
    source_lang_code: str = Form("AUTO"),
    target_lang_code: str = Form("PT-BR"),
):
    """
    Создаёт job, сохраняет файлы, возвращает job_id.
    Сам процесс перевода запустится отдельно через POST /api/start/{job_id}.
    """
    job_id = uuid.uuid4().hex[:12]
    config = {
        "target_lang": target_lang,
        "source_lang": source_lang,
        "target_lang_code": target_lang_code,
        "source_lang_code": source_lang_code,
        "work_title": work_title.strip(),
        "chapter_number": chapter_number.strip(),
        "font_path": font_path,
        "debug": debug,
        "llm_model": llm_model.strip() or None,
        "llm_debug": llm_debug,
        "fast_mode": fast_mode,
    }
    storage_name = _job_storage_name(job_id, config)
    upload_dir = UPLOADS_DIR / storage_name
    result_dir = RESULTS_DIR / storage_name
    upload_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    for index, f in enumerate(files, start=1):
        safe_name = _safe_upload_filename(f.filename, index, f.content_type)
        if not safe_name:
            continue
        target = upload_dir / safe_name
        with open(target, "wb") as out:
            shutil.copyfileobj(f.file, out)

    saved = sorted(upload_dir.iterdir(), key=lambda p: mt.natural_key(p.name))
    if not saved:
        raise HTTPException(400, "Не загружено ни одной валидной картинки")

    JOBS[job_id] = {
        "status": "ready",
        "config": config,
        "storage_name": storage_name,
        "total_pages": len(saved),
        "total": len(saved),
        "completed": 0,
        "pages": [],
        "stats": None,
        "queue": asyncio.Queue(),
    }
    _write_job_meta(job_id, JOBS[job_id])
    return {"job_id": job_id, "total_pages": len(saved), "storage_name": storage_name, "config": config}


def _box_from_bubble(bubble: dict, prefix: str = "") -> tuple[int, int, int, int]:
    if prefix:
        x = bubble.get(f"{prefix}_x", bubble.get("x", 0))
        y = bubble.get(f"{prefix}_y", bubble.get("y", 0))
        w = bubble.get(f"{prefix}_w", bubble.get(f"{prefix}_width", bubble.get("width", 1)))
        h = bubble.get(f"{prefix}_h", bubble.get(f"{prefix}_height", bubble.get("height", 1)))
    else:
        x = bubble.get("x", 0)
        y = bubble.get("y", 0)
        w = bubble.get("w", bubble.get("width", 1))
        h = bubble.get("h", bubble.get("height", 1))
    return int(x or 0), int(y or 0), max(1, int(w or 1)), max(1, int(h or 1))


def _clamp_box(x: int, y: int, w: int, h: int, width: int, height: int) -> tuple[int, int, int, int]:
    x0 = max(0, min(width - 1, int(x)))
    y0 = max(0, min(height - 1, int(y)))
    x1 = max(x0 + 1, min(width, int(x + w)))
    y1 = max(y0 + 1, min(height, int(y + h)))
    return x0, y0, x1 - x0, y1 - y0


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (0.2126 * r) + (0.7152 * g) + (0.0722 * b)


def _median_rgb(pixels: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not pixels:
        return (255, 255, 255)
    pixels = sorted(pixels, key=lambda p: _luminance(p))
    return pixels[len(pixels) // 2]


def _sample_bubble_background(img: Image.Image, bubble: dict) -> tuple[int, int, int]:
    """Return the dominant visible fill color around the original text."""
    width, height = img.size
    x, y, w, h = _clamp_box(*_box_from_bubble(bubble, "text"), width, height)
    box = (x, y, min(width, x + w), min(height, y + h))
    crop = img.crop(box).convert("RGB")
    crop_width, crop_height = crop.size
    border_x = max(2, int(crop_width * 0.18))
    border_y = max(2, int(crop_height * 0.18))
    all_pixels = list(crop.getdata())
    pixels = [
        pixel for idx, pixel in enumerate(all_pixels)
        if (idx % crop_width) < border_x
        or (idx % crop_width) >= crop_width - border_x
        or (idx // crop_width) < border_y
        or (idx // crop_width) >= crop_height - border_y
    ]
    if len(pixels) < 24:
        pixels = all_pixels
    if not pixels:
        return (255, 255, 255)

    step = max(1, len(pixels) // 6000)
    sampled = pixels[::step]
    buckets = Counter((r // 24, g // 24, b // 24) for r, g, b in sampled)
    bucket = buckets.most_common(1)[0][0]
    chosen = [
        (r, g, b) for r, g, b in sampled
        if (r // 24, g // 24, b // 24) == bucket
    ] or sampled
    chosen.sort(key=lambda p: (p[0], p[1], p[2]))
    return chosen[len(chosen) // 2]


def _text_color_for_bg(rgb: tuple[int, int, int]) -> str:
    return "#111111" if _luminance(rgb) >= 145 else "#f8f8f8"


def _rgb_css(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"rgb({r}, {g}, {b})"


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((int(x) - int(y)) ** 2 for x, y in zip(a, b)) ** 0.5


def _sample_patch_median(img: Image.Image, cx: int, cy: int, radius: int = 3) -> tuple[int, int, int]:
    width, height = img.size
    x0 = max(0, cx - radius)
    y0 = max(0, cy - radius)
    x1 = min(width, cx + radius + 1)
    y1 = min(height, cy + radius + 1)
    return _median_rgb(list(img.crop((x0, y0, x1, y1)).convert("RGB").getdata()))


def _visual_shape_for_bubble(
    img: Image.Image,
    bubble: dict,
    bg: tuple[int, int, int],
    fallback_w: int,
    fallback_h: int,
) -> str:
    width, height = img.size
    tx, ty, tw, th = _clamp_box(*_box_from_bubble(bubble, "text"), width, height)
    x, y, w, h = _expanded_overlay_box(
        {"x": tx, "y": ty, "width": tw, "height": th},
        width,
        height,
    )
    aspect = fallback_w / max(1, fallback_h)
    inset_x = max(2, min(10, w // 12))
    inset_y = max(2, min(10, h // 12))
    corners = [
        _sample_patch_median(img, x + inset_x, y + inset_y),
        _sample_patch_median(img, x + w - inset_x - 1, y + inset_y),
        _sample_patch_median(img, x + inset_x, y + h - inset_y - 1),
        _sample_patch_median(img, x + w - inset_x - 1, y + h - inset_y - 1),
    ]
    corner_matches = sum(1 for pixel in corners if _rgb_distance(pixel, bg) <= 42)

    if corner_matches >= 3:
        return "rect" if 0.78 <= aspect <= 1.28 else "wide" if aspect > 1.28 else "tall"
    if aspect >= 2.75:
        return "wide"
    if aspect <= 0.75:
        return "tall"
    return "oval"


def _sample_text_foreground(img: Image.Image, bubble: dict, bg: tuple[int, int, int]) -> tuple[int, int, int]:
    width, height = img.size
    x, y, w, h = _clamp_box(*_box_from_bubble(bubble, "text"), width, height)
    crop = img.crop((x, y, x + w, y + h)).convert("RGB")
    pixels = list(crop.getdata())
    if not pixels:
        return (17, 17, 17) if _luminance(bg) >= 145 else (248, 248, 248)

    bg_lum = _luminance(bg)
    if bg_lum >= 145:
        candidates = [p for p in pixels if _luminance(p) < bg_lum - 45]
    else:
        candidates = [p for p in pixels if _luminance(p) > bg_lum + 45]

    if len(candidates) < max(12, len(pixels) * 0.01):
        return (17, 17, 17) if bg_lum >= 145 else (248, 248, 248)

    return _median_rgb(candidates)


def _text_mask_for_crop(crop: Image.Image, bg: tuple[int, int, int]):
    arr = mt.np.asarray(crop.convert("RGB"))
    if arr.size == 0:
        return None

    gray = mt.cv2.cvtColor(arr, mt.cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    if h < 3 or w < 3:
        return None

    dark = mt.cv2.adaptiveThreshold(
        gray, 255, mt.cv2.ADAPTIVE_THRESH_GAUSSIAN_C, mt.cv2.THRESH_BINARY_INV, 31, 9
    )
    light = mt.cv2.adaptiveThreshold(
        gray, 255, mt.cv2.ADAPTIVE_THRESH_GAUSSIAN_C, mt.cv2.THRESH_BINARY, 31, 9
    )

    def filtered_components(src):
        count, labels, stats, _ = mt.cv2.connectedComponentsWithStats(src, 8)
        out = mt.np.zeros_like(src)
        image_area = max(1, h * w)
        for label in range(1, count):
            x, y, cw, ch, area = stats[label]
            if area < max(3, image_area * 0.00004):
                continue
            if area > image_area * 0.08:
                continue
            if cw > w * 0.45 or ch > h * 0.45:
                continue
            if ch < 2 or cw < 1:
                continue
            out[labels == label] = 255
        return out

    dark = filtered_components(dark)
    light = filtered_components(light)
    mask = dark if mt.np.count_nonzero(dark) >= mt.np.count_nonzero(light) else light
    if mt.np.count_nonzero(mask) < max(6, h * w * 0.0005):
        return None

    kernel_w = max(2, min(14, w // 36))
    kernel = mt.np.ones((2, kernel_w), dtype="uint8")
    mask = mt.cv2.morphologyEx(mask, mt.cv2.MORPH_CLOSE, kernel)
    mask = mt.cv2.medianBlur(mask, 3)
    return mask


def _runs_from_flags(flags: list[bool], max_gap: int = 1) -> list[tuple[int, int]]:
    runs = []
    start = None
    last = None
    gap = 0
    for idx, active in enumerate(flags):
        if active:
            if start is None:
                start = idx
            last = idx
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                runs.append((start, (last or idx) + 1))
                start = None
                last = None
                gap = 0
    if start is not None:
        runs.append((start, (last or len(flags) - 1) + 1))
    return runs


def _text_layout_from_image(img: Image.Image, bubble: dict, bg: tuple[int, int, int]) -> dict:
    width, height = img.size
    x, y, w, h = _clamp_box(*_box_from_bubble(bubble, "text"), width, height)
    crop = img.crop((x, y, x + w, y + h)).convert("RGB")
    mask = _text_mask_for_crop(crop, bg)
    if mask is None:
        return {
            "text_align": "center",
            "line_count": 1,
            "paragraph_count": 1,
            "text_valign": "middle",
            "detected_font_size": 0,
        }

    crop_h, crop_w = mask.shape
    line_boxes = _text_line_boxes_from_mask(mask)

    if not line_boxes:
        return {
            "text_align": "center",
            "line_count": 1,
            "paragraph_count": 1,
            "text_valign": "middle",
            "detected_font_size": 0,
        }

    centers = [(x0 + x1) / 2 for x0, _, x1, _ in line_boxes]
    avg_center = sum(centers) / len(centers)
    if abs(avg_center - crop_w / 2) <= crop_w * 0.09:
        align = "center"
    elif avg_center < crop_w * 0.45:
        align = "left"
    else:
        align = "right"

    heights = [y1 - y0 for _, y0, _, y1 in line_boxes]
    median_h = sorted(heights)[len(heights) // 2]
    paragraph_count = 1
    for prev, current in zip(line_boxes, line_boxes[1:]):
        gap = current[1] - prev[3]
        if gap > median_h * 1.35:
            paragraph_count += 1

    content_center_y = (line_boxes[0][1] + line_boxes[-1][3]) / 2
    if content_center_y < crop_h * 0.40:
        valign = "top"
    elif content_center_y > crop_h * 0.60:
        valign = "bottom"
    else:
        valign = "middle"

    return {
        "text_align": align,
        "line_count": max(1, min(8, len(line_boxes))),
        "paragraph_count": max(1, min(4, paragraph_count)),
        "text_valign": valign,
        "detected_font_size": max(6, min(72, int(median_h * 1.15))),
    }


def _shadow_for_text(text_rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> str:
    text_lum = _luminance(text_rgb)
    bg_lum = _luminance(bg_rgb)
    if abs(text_lum - bg_lum) >= 80:
        return "none"
    return "0 1px 1px rgba(0,0,0,.55)" if text_lum > 150 else "0 1px 1px rgba(255,255,255,.45)"


def _shape_for_box(w: int, h: int, klass: str = "") -> str:
    if klass == "text_free":
        return "rect"
    aspect = w / max(1, h)
    if aspect >= 2.75:
        return "wide"
    if aspect >= 1.45:
        return "oval"
    if aspect <= 0.75:
        return "tall"
    return "round"


def _intersection_area(a: dict, b: dict) -> int:
    ax, ay, aw, ah = _box_from_bubble(a)
    bx, by, bw, bh = _box_from_bubble(b)
    x0 = max(ax, bx)
    y0 = max(ay, by)
    x1 = min(ax + aw, bx + bw)
    y1 = min(ay + ah, by + bh)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _center_inside(inner: dict, outer: dict) -> bool:
    ix, iy, iw, ih = _box_from_bubble(inner)
    ox, oy, ow, oh = _box_from_bubble(outer)
    cx = ix + iw / 2
    cy = iy + ih / 2
    return ox <= cx <= ox + ow and oy <= cy <= oy + oh


def _box_intersection(a: dict, b: dict, prefix: str = "") -> int:
    ax, ay, aw, ah = _box_from_bubble(a, prefix)
    bx, by, bw, bh = _box_from_bubble(b, prefix)
    x0 = max(ax, bx)
    y0 = max(ay, by)
    x1 = min(ax + aw, bx + bw)
    y1 = min(ay + ah, by + bh)
    return max(0, x1 - x0) * max(0, y1 - y0)


def _box_area(bubble: dict, prefix: str = "") -> int:
    _, _, w, h = _box_from_bubble(bubble, prefix)
    return max(1, w * h)


def _box_overlap_fraction(a: dict, b: dict, prefix: str = "") -> float:
    return _box_intersection(a, b, prefix) / max(1, min(_box_area(a, prefix), _box_area(b, prefix)))


def _box_center_distance_fraction(a: dict, b: dict, prefix: str = "") -> float:
    ax, ay, aw, ah = _box_from_bubble(a, prefix)
    bx, by, bw, bh = _box_from_bubble(b, prefix)
    dx = (ax + aw / 2) - (bx + bw / 2)
    dy = (ay + ah / 2) - (by + bh / 2)
    scale = max(1.0, ((aw + bw + ah + bh) / 4))
    return ((dx * dx + dy * dy) ** 0.5) / scale


def _is_duplicate_overlay_bubble(a: dict, b: dict) -> bool:
    text_overlap = _box_overlap_fraction(a, b, "text")
    if text_overlap >= 0.68:
        return True
    overlay_overlap = _box_overlap_fraction(a, b, "overlay")
    centers_close = _box_center_distance_fraction(a, b, "text") <= 0.22
    return overlay_overlap >= 0.90 and centers_close and text_overlap >= 0.45


def _dedupe_overlay_bubbles(bubbles: list[dict]) -> list[dict]:
    kept: list[dict] = []
    ranked = sorted(
        bubbles,
        key=lambda b: (
            float(b.get("confidence", 0)),
            _box_area(b, "text"),
        ),
        reverse=True,
    )
    for bubble in ranked:
        if any(_is_duplicate_overlay_bubble(bubble, existing) for existing in kept):
            continue
        kept.append(bubble)
    return sorted(kept, key=mt.reading_order)


def _looks_like_page_or_panel_box(bubble: dict, image_width: int, image_height: int) -> bool:
    x, y, w, h = _box_from_bubble(bubble)
    image_area = max(1, image_width * image_height)
    area = w * h
    if area > image_area * 0.42:
        return True
    if w > image_width * 0.92 and h > image_height * 0.18:
        return True
    if h > image_height * 0.92 and w > image_width * 0.18:
        return True
    touches_edges = sum((
        x <= 3,
        y <= 3,
        x + w >= image_width - 3,
        y + h >= image_height - 3,
    ))
    return touches_edges >= 3 and area > image_area * 0.18


def _union_bubble_boxes(bubbles: list[dict]) -> tuple[int, int, int, int]:
    x0 = min(_box_from_bubble(b)[0] for b in bubbles)
    y0 = min(_box_from_bubble(b)[1] for b in bubbles)
    x1 = max(_box_from_bubble(b)[0] + _box_from_bubble(b)[2] for b in bubbles)
    y1 = max(_box_from_bubble(b)[1] + _box_from_bubble(b)[3] for b in bubbles)
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)


def _split_text_groups_by_vertical_gap(group: list[dict], container: dict) -> list[list[dict]]:
    if len(group) <= 1:
        return [group]
    if not WEB_SPLIT_TEXT_GROUPS:
        return [group]

    ordered = sorted(group, key=lambda b: (_box_from_bubble(b)[1], _box_from_bubble(b)[0]))
    heights = sorted(_box_from_bubble(item)[3] for item in ordered)
    median_h = heights[len(heights) // 2]
    split_gap = max(12, median_h * 0.85)

    clusters: list[list[dict]] = [[ordered[0]]]
    previous_y = _box_from_bubble(ordered[0])[1]
    previous_h = _box_from_bubble(ordered[0])[3]

    for item in ordered[1:]:
        x, y, w, h = _box_from_bubble(item)
        prev_x, _, prev_w, _ = _box_from_bubble(clusters[-1][-1])
        prev_center_x = prev_x + prev_w / 2
        center_x = x + w / 2
        gap_y = y - (previous_y + previous_h)
        gap_x = x - (prev_x + prev_w)
        vertical_overlap = max(0, min(y + h, previous_y + previous_h) - max(y, previous_y))
        overlap_ratio = vertical_overlap / max(1, min(h, previous_h))
        center_shift = abs(center_x - prev_center_x)
        clearly_new_block = (
            gap_y > split_gap
            or (
                gap_y > median_h * 0.35
                and center_shift > max(24, median_h * 1.15)
                and overlap_ratio < 0.55
            )
            or (
                y - previous_y > max(median_h * 2.35, previous_h * 1.20)
                and overlap_ratio < 0.55
            )
        )
        if clearly_new_block:
            clusters.append([item])
        else:
            clusters[-1].append(item)
        previous_y = y
        previous_h = h

    return clusters


def _overlay_for_text_cluster(
    cluster: list[dict],
    container: dict,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    tx, ty, tw, th = _clamp_box(*_union_bubble_boxes(cluster), image_width, image_height)
    return _expanded_overlay_box({"x": tx, "y": ty, "width": tw, "height": th}, image_width, image_height)


def _expanded_overlay_box(text_box: dict, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    x, y, w, h = _box_from_bubble(text_box)
    aspect = w / max(1, h)
    pad_x = max(5, int(w * 0.10), int(h * 0.08))
    pad_y = max(4, int(h * 0.12), int(w * 0.025))
    if aspect < 0.9:
        pad_x = max(pad_x, int(h * 0.18))
    elif aspect > 2.4:
        pad_y = max(pad_y, int(w * 0.04))
    return _clamp_box(x - pad_x, y - pad_y, w + pad_x * 2, h + pad_y * 2, image_width, image_height)


def _overlaps_existing_text(candidate: dict, existing: list[dict]) -> bool:
    cx, cy, cw, ch = _box_from_bubble(candidate, "text")
    candidate_area = max(1, cw * ch)
    for bubble in existing:
        overlap = _intersection_area(candidate, bubble)
        if overlap / candidate_area > 0.38:
            return True
        if _box_overlap_fraction(candidate, bubble, "text") > 0.55:
            return True
    return False


def _fallback_high_contrast_text_regions(
    image_pil: Image.Image,
    existing: list[dict],
    image_width: int,
    image_height: int,
) -> list[dict]:
    rgb = mt.np.asarray(image_pil.convert("RGB"))
    if rgb.size == 0:
        return []

    gray = mt.cv2.cvtColor(rgb, mt.cv2.COLOR_RGB2GRAY)
    image_area = max(1, image_width * image_height)
    masks = [
        mt.cv2.adaptiveThreshold(gray, 255, mt.cv2.ADAPTIVE_THRESH_GAUSSIAN_C, mt.cv2.THRESH_BINARY_INV, 31, 8),
        mt.cv2.adaptiveThreshold(gray, 255, mt.cv2.ADAPTIVE_THRESH_GAUSSIAN_C, mt.cv2.THRESH_BINARY, 31, 8),
    ]
    region_boxes: list[tuple[int, int, int, int]] = []

    for mask in masks:
        count, labels, stats, _ = mt.cv2.connectedComponentsWithStats(mask, 8)
        clean = mt.np.zeros_like(mask)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if area < max(5, image_area * 0.000006):
                continue
            if area > image_area * 0.010:
                continue
            if h < 5 or w < 2:
                continue
            if h > image_height * 0.12 or w > image_width * 0.48:
                continue
            if w > image_width * 0.24 and h < 9:
                continue
            clean[labels == label] = 255

        if mt.np.count_nonzero(clean) < 10:
            continue

        kernel_w = max(9, min(42, image_width // 22))
        kernel_h = max(3, min(14, image_height // 130))
        kernel = mt.cv2.getStructuringElement(mt.cv2.MORPH_RECT, (kernel_w, kernel_h))
        grouped = mt.cv2.morphologyEx(clean, mt.cv2.MORPH_CLOSE, kernel, iterations=1)
        grouped = mt.cv2.dilate(grouped, mt.cv2.getStructuringElement(mt.cv2.MORPH_RECT, (3, 3)), iterations=1)
        count, labels, stats, _ = mt.cv2.connectedComponentsWithStats(grouped, 8)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            box_area = max(1, w * h)
            density = area / box_area
            if w < 24 or h < 10:
                continue
            if box_area > image_area * 0.16:
                continue
            if density < 0.025 or density > 0.72:
                continue
            if w > image_width * 0.78 and h > image_height * 0.18:
                continue
            region_boxes.append(_clamp_box(x - 4, y - 3, w + 8, h + 6, image_width, image_height))

    fallback: list[dict] = []
    for x, y, w, h in sorted(region_boxes, key=lambda box: (box[1], box[0])):
        candidate = {
            "class": "text_free",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "text_x": x,
            "text_y": y,
            "text_w": w,
            "text_h": h,
            "confidence": 0.24,
        }
        if _looks_like_page_or_panel_box(candidate, image_width, image_height):
            continue
        if _overlaps_existing_text(candidate, existing + fallback):
            continue
        ox, oy, ow, oh = _expanded_overlay_box(candidate, image_width, image_height)
        candidate["overlay_x"] = ox
        candidate["overlay_y"] = oy
        candidate["overlay_w"] = ow
        candidate["overlay_h"] = oh
        candidate["shape"] = "soft"
        fallback.append(candidate)

    return fallback


def _with_optional_fallback_text_regions(
    image_pil: Image.Image,
    text_bubbles: list[dict],
    image_width: int,
    image_height: int,
) -> list[dict]:
    if not WEB_FALLBACK_TEXT_REGIONS:
        return text_bubbles
    if len(text_bubbles) > 2:
        return text_bubbles
    fallback = _fallback_high_contrast_text_regions(image_pil, text_bubbles, image_width, image_height)
    return text_bubbles + fallback[: max(0, 4 - len(text_bubbles))]


def _attach_overlay_boxes(detections: list[dict], image_width: int, image_height: int) -> list[dict]:
    containers = [
        b for b in detections
        if b.get("class") == "bubble" and not _looks_like_page_or_panel_box(b, image_width, image_height)
    ]
    text_boxes = [
        b for b in detections
        if b.get("class") in ("text_bubble", "text_free")
        and not _looks_like_page_or_panel_box(b, image_width, image_height)
    ]
    image_area = max(1, image_width * image_height)

    prepared = []

    if text_boxes:
        assignments: dict[int, list[dict]] = {}
        assigned_containers: dict[int, dict] = {}
        unassigned: list[dict] = []

        for source in sorted(text_boxes, key=mt.reading_order):
            best = None
            best_score = 0.0
            source_area = max(1, int(source.get("width", 1)) * int(source.get("height", 1)))
            for container in containers:
                container_area = max(1, int(container.get("width", 1)) * int(container.get("height", 1)))
                if container_area > image_area * 0.55:
                    continue
                if container_area < source_area * 0.80:
                    continue
                area_ratio = container_area / source_area
                width_ratio = int(container.get("width", 1)) / max(1, int(source.get("width", 1)))
                height_ratio = int(container.get("height", 1)) / max(1, int(source.get("height", 1)))
                if area_ratio > 28 or width_ratio > 8 or height_ratio > 8:
                    continue

                overlap = _intersection_area(source, container) / source_area
                center_inside = _center_inside(source, container)
                if overlap < 0.25 and not center_inside:
                    continue
                score = overlap + (0.35 if center_inside else 0) + float(container.get("confidence", 0)) * 0.08
                if score > best_score:
                    best = container
                    best_score = score

            if best is None:
                unassigned.append(source)
            else:
                key = id(best)
                assignments.setdefault(key, []).append(source)
                assigned_containers[key] = best

        for key, group in assignments.items():
            container = assigned_containers[key]
            bx, by, bw, bh = _box_from_bubble(container)
            clusters = _split_text_groups_by_vertical_gap(group, container)
            use_parent_balloon = len(clusters) == 1
            for cluster in clusters:
                tx, ty, tw, th = _clamp_box(*_union_bubble_boxes(cluster), image_width, image_height)
                ox, oy, ow, oh = _overlay_for_text_cluster(cluster, container, image_width, image_height)
                item = dict(container)
                item["class"] = "text_bubble"
                if use_parent_balloon:
                    item["balloon_x"] = bx
                    item["balloon_y"] = by
                    item["balloon_w"] = bw
                    item["balloon_h"] = bh
                item["x"] = tx
                item["y"] = ty
                item["width"] = tw
                item["height"] = th
                item["text_x"] = tx
                item["text_y"] = ty
                item["text_w"] = tw
                item["text_h"] = th
                item["overlay_x"] = ox
                item["overlay_y"] = oy
                item["overlay_w"] = ow
                item["overlay_h"] = oh
                item["shape"] = "soft"
                item["confidence"] = max(float(part.get("confidence", 0)) for part in cluster)
                prepared.append(item)

        text_boxes = unassigned
    elif containers:
        text_boxes = containers

    for source in text_boxes:
        item = dict(source)
        item["text_x"] = item.get("x", 0)
        item["text_y"] = item.get("y", 0)
        item["text_w"] = item.get("width", 1)
        item["text_h"] = item.get("height", 1)

        if item.get("class") == "bubble":
            ox, oy, ow, oh = _expanded_overlay_box(item, image_width, image_height)
            item["overlay_x"] = ox
            item["overlay_y"] = oy
            item["overlay_w"] = ow
            item["overlay_h"] = oh
            item["shape"] = "soft"
            prepared.append(item)
            continue

        best = None
        best_score = 0.0
        source_area = max(1, int(item["text_w"]) * int(item["text_h"]))
        for container in containers:
            if container is source:
                continue
            container_area = max(1, int(container.get("width", 1)) * int(container.get("height", 1)))
            area_ratio = container_area / source_area
            width_ratio = int(container.get("width", 1)) / max(1, int(item["text_w"]))
            height_ratio = int(container.get("height", 1)) / max(1, int(item["text_h"]))
            if container_area < source_area * 1.15:
                continue
            if area_ratio > 14 or width_ratio > 3.5 or height_ratio > 3.8:
                continue
            overlap = _intersection_area(item, container) / source_area
            if overlap < 0.35 and not _center_inside(item, container):
                continue
            score = overlap + min(0.5, container_area / source_area / 20) + float(container.get("confidence", 0)) * 0.05
            if score > best_score:
                best = container
                best_score = score

        if best:
            bx, by, bw, bh = _box_from_bubble(best)
            item["balloon_x"] = bx
            item["balloon_y"] = by
            item["balloon_w"] = bw
            item["balloon_h"] = bh
            ox, oy, ow, oh = _expanded_overlay_box(item, image_width, image_height)
        else:
            ox, oy, ow, oh = _expanded_overlay_box(item, image_width, image_height)

        item["overlay_x"] = ox
        item["overlay_y"] = oy
        item["overlay_w"] = ow
        item["overlay_h"] = oh
        item["shape"] = "soft"
        prepared.append(item)

    return _dedupe_overlay_bubbles(prepared)


def _bubble_response_payload(image_path: Path, bubbles: list[dict]) -> dict:
    with Image.open(image_path) as pil:
        img = pil.convert("RGB")
        image_width, image_height = img.size
        out_bubbles = []
        for i, b in enumerate(bubbles, start=1):
            bg = _sample_bubble_background(img, b)
            text_rgb = _sample_text_foreground(img, b, bg)
            layout = _text_layout_from_image(img, b, bg)
            tx, ty, tw, th = _box_from_bubble(b, "text")
            if all(k in b for k in ("overlay_x", "overlay_y", "overlay_w", "overlay_h")):
                x, y, w, h = _clamp_box(
                    int(b.get("overlay_x", tx)),
                    int(b.get("overlay_y", ty)),
                    int(b.get("overlay_w", tw)),
                    int(b.get("overlay_h", th)),
                    image_width,
                    image_height,
                )
            else:
                x, y, w, h = _expanded_overlay_box(
                    {"x": tx, "y": ty, "width": tw, "height": th},
                    image_width,
                    image_height,
                )
            out_bubbles.append({
                "idx": i,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "balloon_x": b.get("balloon_x"),
                "balloon_y": b.get("balloon_y"),
                "balloon_w": b.get("balloon_w"),
                "balloon_h": b.get("balloon_h"),
                "text_x": tx,
                "text_y": ty,
                "text_w": tw,
                "text_h": th,
                "class": b.get("class", ""),
                "shape": _visual_shape_for_bubble(img, b, bg, w, h),
                "text": b.get("text", ""),
                "translation": b.get("translation", ""),
                "speaker": b.get("speaker", "unknown"),
                "gender": b.get("gender", "unknown"),
                "font_size": b.get("font_size"),
                "background_color": _rgb_css(bg),
                "text_color": _rgb_css(text_rgb),
                "text_shadow": _shadow_for_text(text_rgb, bg),
                **layout,
            })
    return {
        "image_width": image_width,
        "image_height": image_height,
        "bubbles": out_bubbles,
    }


def _text_line_boxes_from_mask(mask, min_area_ratio: float = 0.002) -> list[tuple[int, int, int, int]]:
    crop_h, crop_w = mask.shape
    row_counts = (mask > 0).sum(axis=1)
    active_rows = row_counts > max(2, crop_w * 0.018)
    line_runs = _runs_from_flags(active_rows.tolist(), max_gap=max(1, crop_h // 90))

    line_boxes = []
    for y0, y1 in line_runs:
        if y1 - y0 < 2:
            continue
        segment = mask[y0:y1, :] > 0
        cols = mt.np.where(segment.any(axis=0))[0]
        if cols.size < 2:
            continue
        x0 = int(cols[0])
        x1 = int(cols[-1]) + 1
        if (x1 - x0) * (y1 - y0) < max(8, crop_w * crop_h * min_area_ratio):
            continue
        line_boxes.append((x0, y0, x1, y1))
    return line_boxes


def _split_bubble_by_visual_text(
    img: Image.Image,
    bubble: dict,
    image_width: int,
    image_height: int,
) -> list[dict]:
    tx, ty, tw, th = _clamp_box(*_box_from_bubble(bubble, "text"), image_width, image_height)
    area_ratio = (tw * th) / max(1, image_width * image_height)
    auto_split_free_text = bubble.get("class") == "text_free"
    if not WEB_SPLIT_VISUAL_TEXT and not auto_split_free_text:
        return [bubble]

    bg = _sample_bubble_background(img, bubble)
    crop = img.crop((tx, ty, tx + tw, ty + th)).convert("RGB")
    mask = _text_mask_for_crop(crop, bg)
    if mask is None:
        return [bubble]

    line_boxes = _text_line_boxes_from_mask(mask)
    if len(line_boxes) <= 1:
        return [bubble]

    heights = sorted(y1 - y0 for _, y0, _, y1 in line_boxes)
    median_h = heights[len(heights) // 2]
    split_gap = max(10, min(median_h * 1.35, th * 0.08))
    clusters: list[list[tuple[int, int, int, int]]] = [[line_boxes[0]]]
    for line in line_boxes[1:]:
        previous = clusters[-1][-1]
        prev_center = (previous[0] + previous[2]) / 2
        center = (line[0] + line[2]) / 2
        gap_y = line[1] - previous[3]
        center_shift = abs(center - prev_center)
        if gap_y > split_gap or (gap_y > median_h * 0.55 and center_shift > tw * 0.24):
            clusters.append([line])
        else:
            clusters[-1].append(line)

    if len(clusters) == 1 and len(line_boxes) >= 6:
        gaps = [
            (line_boxes[i][1] - line_boxes[i - 1][3], i)
            for i in range(1, len(line_boxes))
        ]
        largest_gap, split_at = max(gaps, key=lambda item: item[0])
        enough_lines_each_side = split_at >= 2 and (len(line_boxes) - split_at) >= 2
        tall_text_block = th > image_height * 0.12 or th > median_h * 5.0
        meaningful_gap = largest_gap > max(8, median_h * 0.90)
        if enough_lines_each_side and tall_text_block and meaningful_gap:
            clusters = [line_boxes[:split_at], line_boxes[split_at:]]

    def cluster_item(cluster):
        x0 = min(line[0] for line in cluster)
        y0 = min(line[1] for line in cluster)
        x1 = max(line[2] for line in cluster)
        y1 = max(line[3] for line in cluster)
        pad_x = max(3, min(16, int((x1 - x0) * 0.05)))
        pad_y = max(2, min(12, int((y1 - y0) * 0.08)))
        text_item = {
            "x": tx + max(0, x0 - pad_x),
            "y": ty + max(0, y0 - pad_y),
            "width": max(1, min(tw, x1 - x0 + pad_x * 2)),
            "height": max(1, min(th, y1 - y0 + pad_y * 2)),
        }
        ox, oy, ow, oh = _expanded_overlay_box(text_item, image_width, image_height)
        item = dict(bubble)
        item["x"] = text_item["x"]
        item["y"] = text_item["y"]
        item["width"] = text_item["width"]
        item["height"] = text_item["height"]
        item["text_x"] = text_item["x"]
        item["text_y"] = text_item["y"]
        item["text_w"] = text_item["width"]
        item["text_h"] = text_item["height"]
        item["overlay_x"] = ox
        item["overlay_y"] = oy
        item["overlay_w"] = ow
        item["overlay_h"] = oh
        item["shape"] = "soft"
        return item

    if len(clusters) <= 1:
        refined = cluster_item(line_boxes)
        original_area = max(1, tw * th)
        refined_area = max(1, int(refined["width"]) * int(refined["height"]))
        if refined_area < original_area * 0.82:
            return [refined]
        return [bubble]

    split = []
    for cluster in clusters:
        split.append(cluster_item(cluster))

    return split


def _read_cv_image(image_path: Path):
    img_cv = mt.cv2.imread(str(image_path))
    if img_cv is None:
        img_cv = mt.cv2.imdecode(mt.np.fromfile(str(image_path), dtype=mt.np.uint8), mt.cv2.IMREAD_COLOR)
    if img_cv is None:
        raise ValueError("Could not read uploaded image")
    return img_cv


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_put_limited(cache: dict, key, value, limit: int = WEB_CACHE_LIMIT):
    cache[key] = value
    while len(cache) > limit:
        cache.pop(next(iter(cache)))


def _bubble_cache_box(bubble: dict) -> tuple[int, int, int, int]:
    return _box_from_bubble(bubble)


def _detect_text_bubbles(image_path: Path) -> tuple[object, list[dict]]:
    img_cv = _read_cv_image(image_path)
    image_pil = Image.fromarray(mt.cv2.cvtColor(img_cv, mt.cv2.COLOR_BGR2RGB))
    bubbles = mt.detect_bubbles(image_pil, threshold=WEB_DETECTION_THRESHOLD)
    text_bubbles = _attach_overlay_boxes(bubbles, image_pil.size[0], image_pil.size[1])
    text_bubbles = _with_optional_fallback_text_regions(image_pil, text_bubbles, image_pil.size[0], image_pil.size[1])
    split_bubbles = []
    for bubble in text_bubbles:
        split_bubbles.extend(_split_bubble_by_visual_text(image_pil.convert("RGB"), bubble, image_pil.size[0], image_pil.size[1]))
    return img_cv, sorted(_dedupe_overlay_bubbles(split_bubbles), key=mt.reading_order)


def _detect_text_bubbles_cached(image_path: Path, image_key: str) -> tuple[object, list[dict]]:
    img_cv = _read_cv_image(image_path)
    cached = LIVE_DETECTION_CACHE.get(image_key)
    if cached:
        return img_cv, [dict(bubble) for bubble in cached]

    image_pil = Image.fromarray(mt.cv2.cvtColor(img_cv, mt.cv2.COLOR_BGR2RGB))
    bubbles = mt.detect_bubbles(image_pil, threshold=WEB_DETECTION_THRESHOLD)
    text_bubbles = _attach_overlay_boxes(bubbles, image_pil.size[0], image_pil.size[1])
    text_bubbles = _with_optional_fallback_text_regions(image_pil, text_bubbles, image_pil.size[0], image_pil.size[1])
    split_bubbles = []
    rgb = image_pil.convert("RGB")
    for bubble in text_bubbles:
        split_bubbles.extend(_split_bubble_by_visual_text(rgb, bubble, image_pil.size[0], image_pil.size[1]))
    result = sorted(_dedupe_overlay_bubbles(split_bubbles), key=mt.reading_order)
    _cache_put_limited(LIVE_DETECTION_CACHE, image_key, [dict(bubble) for bubble in result])
    return img_cv, result


def _clean_visible_text_preserve_lines(raw: str) -> str:
    text = raw or ""
    text = re.sub(r"```[a-zA-Z0-9_-]*\s*", "", text)
    text = text.replace("```", "").replace("`", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip().strip("\"'")
        line = re.sub(r"^(text|ocr|transcription)\s*:\s*", "", line, flags=re.I)
        lines.append(line)

    compact = []
    previous_blank = False
    for line in lines:
        if not line:
            if compact and not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False

    while compact and not compact[-1]:
        compact.pop()
    return _remove_duplicate_dialogue_lines("\n".join(compact)).strip()


def _fold_for_filter(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return folded.lower()


def _has_prompt_echo_fragment(text: str) -> bool:
    folded = _fold_for_filter(text)
    return any(fragment in folded for fragment in PROMPT_ECHO_BLOCKED_FRAGMENTS)


def _has_visual_failure_fragment(text: str) -> bool:
    folded = _fold_for_filter(text)
    return any(fragment in folded for fragment in VISUAL_FAILURE_BLOCKED_FRAGMENTS)


def _normalized_dialogue_line(text: str) -> str:
    folded = _fold_for_filter(text)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _dialogue_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold_for_filter(text))


def _has_repeated_ngram_noise(text: str) -> bool:
    tokens = [token for token in _dialogue_tokens(text) if len(token) > 1]
    if len(tokens) < 8:
        return False

    for size in (5, 4, 3, 2):
        if len(tokens) < size * 2:
            continue
        grams = [" ".join(tokens[i:i + size]) for i in range(0, len(tokens) - size + 1)]
        gram, count = Counter(grams).most_common(1)[0]
        if not gram or count < 2:
            continue
        coverage = (count * size) / max(1, len(tokens))
        if (size >= 3 and coverage >= 0.34) or (size == 2 and count >= 3 and coverage >= 0.36):
            return True

    normalized = _normalized_dialogue_line(text)
    chunks = [chunk.strip() for chunk in re.split(r"\b(?:e|and|mas|but)\b|[.;:!?]+", normalized) if chunk.strip()]
    if len(chunks) >= 4:
        counts = Counter(chunks)
        if any(len(chunk) >= 8 and count >= 3 for chunk, count in counts.items()):
            return True
    return False


def _collapse_repeated_word_noise(line: str) -> str:
    previous = None
    current = line
    word = r"([A-Za-z0-9À-ÿ']{3,})"
    while previous != current:
        previous = current
        current = re.sub(rf"\b{word}(?:[\s,;:/-]+\1\b){{2,}}", r"\1", current, flags=re.I)
        current = re.sub(r"\b([A-Za-z0-9À-ÿ']{5,})\s+\1\b", r"\1", current, flags=re.I)
    return re.sub(r"\s+([,.;:!?])", r"\1", current).strip()


def _remove_duplicate_dialogue_lines(text: str) -> str:
    lines = text.replace("\r", "\n").split("\n")
    result: list[str] = []
    recent: list[str] = []
    previous_blank = False
    for raw_line in lines:
        line = _collapse_repeated_word_noise(raw_line.strip())
        if not line:
            if result and not previous_blank:
                result.append("")
            previous_blank = True
            continue

        normalized = _normalized_dialogue_line(line)
        if not normalized:
            continue
        if normalized in recent:
            continue
        if len(normalized) <= 14 and any(
            normalized != other and normalized in other and len(other) >= len(normalized) * 2
            for other in recent
        ):
            continue
        result.append(line)
        recent.append(normalized)
        recent = recent[-6:]
        previous_blank = False

    while result and not result[-1]:
        result.pop()
    return "\n".join(result).strip()


def _join_dialogue_lines(lines: list[str]) -> str:
    current = ""
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if not current:
            current = line
            continue

        if current.endswith("-"):
            prefix = current[:-1].strip()
            if 1 <= len(prefix) <= 3 and line.lower().startswith(prefix.lower()):
                current = current.rstrip() + line.lstrip()
            else:
                current = current[:-1].rstrip() + line.lstrip()
        elif re.match(r"^[,.;:!?%)}\]\u2026]", line):
            current = current.rstrip() + line
        elif re.search(r"[(\[{¿¡]$", current):
            current = current.rstrip() + line.lstrip()
        else:
            current = f"{current.rstrip()} {line.lstrip()}"

    current = re.sub(r"\s+([,.;:!?%)}\]\u2026])", r"\1", current)
    current = re.sub(r"([({\[\u00bf\u00a1])\s+", r"\1", current)
    current = re.sub(r"\.{3,}", "...", current)
    current = re.sub(r"\s+", " ", current).strip()
    return _collapse_repeated_word_noise(current)


def _merge_clean_lines_to_paragraphs(cleaned: str) -> str:
    if not cleaned:
        return ""

    paragraphs = re.split(r"\n\s*\n+", cleaned)
    merged: list[str] = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
        if not lines:
            continue
        merged.append(_join_dialogue_lines(lines))
    return "\n\n".join(part for part in merged if part).strip()


def _merge_visual_lines_to_paragraphs(text: str) -> str:
    cleaned = _remove_duplicate_dialogue_lines(_clean_visible_text_preserve_lines(text))
    return _merge_clean_lines_to_paragraphs(cleaned)


def _looks_like_portuguese_target(target_lang: str) -> bool:
    folded = _fold_for_filter(target_lang)
    return "portuguese" in folded or "portugues" in folded or "brazil" in folded or "brasil" in folded or folded in {"pt", "pt-br", "pt_br"}


def _fallback_short_expression_translation(text: str, target_lang: str) -> str:
    if not _looks_like_portuguese_target(target_lang):
        return ""
    normalized = _normalized_dialogue_line(re.sub(r"\b([a-zA-Z])[- ]+(?=[a-zA-Z])", "", text or ""))
    replacements = {
        "huh": "Ha?!",
        "huhuh": "Ha?!",
        "huh huh": "Ha?!",
        "uh": "Uh...",
        "damn": "Droga!",
        "damn it": "Droga!!",
        "what": "O que?!",
        "th that s": "I-isso...!",
        "th thats": "I-isso...!",
        "thats": "I-isso...!",
        "that s": "I-isso...!",
    }
    return replacements.get(normalized, "")


def _translation_quality_instruction(target_lang: str) -> str:
    if _looks_like_portuguese_target(target_lang):
        return (
            "Use fluent Brazilian Portuguese word order. Translate compound noun phrases idiomatically, "
            "for example 'Northern Great Plains' should become 'Grandes Planícies do Norte', not a word-by-word order. "
            "Avoid literal calques, fragments, and repeated clauses."
        )
    return (
        "Use fluent natural word order in the target language. Translate compound noun phrases idiomatically, "
        "not word-by-word. Avoid fragments, repeated clauses, and literal calques."
    )


def _postprocess_live_translation(text: str, target_lang: str) -> str:
    cleaned = _clean_live_translation(text)
    if _looks_like_portuguese_target(target_lang):
        cleaned = re.sub(
            r"\bplan[ií]cies?\s+(?:do\s+)?norte\s+grandes?\b",
            "Grandes Planícies do Norte",
            cleaned,
            flags=re.I,
        )
        cleaned = re.sub(
            r"\bgrandes?\s+plan[ií]cies?\s+norte\b",
            "Grandes Planícies do Norte",
            cleaned,
            flags=re.I,
        )
    return cleaned.strip()


def _translation_suspicious_for_source(source_text: str, translation: str, target_lang: str) -> bool:
    if _is_bad_live_translation(translation):
        return True
    source_tokens = _dialogue_tokens(source_text)
    translation_tokens = _dialogue_tokens(translation)
    if len(source_tokens) >= 8 and len(translation_tokens) <= max(3, int(len(source_tokens) * 0.30)):
        return True
    if len(source_tokens) >= 12 and len(translation_tokens) <= max(4, int(len(source_tokens) * 0.38)):
        return True
    if _looks_like_portuguese_target(target_lang):
        folded = _fold_for_filter(translation)
        if re.search(r"\b(said|says|master)\b", folded):
            return True
    return False


def _ocr_region_preserve_layout(img_cv, bubble: dict, index: int) -> str:
    x, y, w, h = _box_from_bubble(bubble)
    crops_dir = Path(getattr(mt, "CROPS_DIR", "crops"))
    crops_dir.mkdir(parents=True, exist_ok=True)

    processed = mt.preprocess_crop(img_cv, x, y, w, h)
    crop_path = crops_dir / f"web_bubble_{index:02d}.png"
    mt.cv2.imwrite(str(crop_path), processed)
    raw = mt.ollama(
        "glm-ocr:latest",
        (
            "OCR this crop. Output only clearly visible printed text. "
            "Preserve line breaks. If unreadable, output nothing."
        ),
        str(crop_path),
        timeout=60,
        num_predict=260,
        temperature=0.0,
    )
    cleaned = _remove_duplicate_dialogue_lines(_clean_visible_text_preserve_lines(raw))
    if cleaned and not _is_bad_bubble_ocr(cleaned):
        print(f"     [OCR web] bubble {index}: {cleaned[:80]!r}")
        return cleaned

    processed_retry = mt.preprocess_crop_minimal(img_cv, x, y, w, h)
    retry_path = crops_dir / f"web_bubble_{index:02d}_retry.png"
    mt.cv2.imwrite(str(retry_path), processed_retry)
    raw_retry = mt.ollama(
        "glm-ocr:latest",
        (
            "Read only the clearly visible printed text. "
            "Preserve line breaks. If there is no readable text, output nothing."
        ),
        str(retry_path),
        timeout=60,
        num_predict=300,
        temperature=0.0,
    )
    retry = _remove_duplicate_dialogue_lines(_clean_visible_text_preserve_lines(raw_retry))
    final = ""
    for candidate in sorted((retry, cleaned), key=len, reverse=True):
        if candidate and not _is_bad_bubble_ocr(candidate):
            final = candidate
            break
    if not final:
        rejected = retry or cleaned
        print(f"     [OCR web discard] bubble {index}: {rejected[:80]!r}")
        return ""
    print(f"     [OCR web retry] bubble {index}: {final[:80]!r}")
    return final


SLANG_ADAPTATION_GUIDES = {
    "off": (
        "Slang adaptation: disabled. Translate faithfully and naturally, but do not add extra slang, memes, jokes, or regionalized expressions "
        "that are not implied by the source."
    ),
    "literal": (
        "Slang adaptation: literal. Keep the meaning close to the source, preserve cultural terms and honorifics when useful, "
        "and avoid adding modern slang that is not implied by the original."
    ),
    "faithful_global": (
        "Slang adaptation: faithful global localization. Use natural modern wording, but keep the original culture, hierarchy, "
        "formality, jokes, and character voice. Avoid region-specific slang unless the source clearly has it."
    ),
    "natural_br": (
        "Slang adaptation: natural Brazilian Portuguese. Make dialogue sound fluent for Brazilian manga/manhwa readers, with light, "
        "natural colloquial phrasing. Do not force memes or excessive slang."
    ),
    "br_2026": (
        "Slang adaptation: Brazil 2026. Use natural Brazilian Portuguese for manga/manhwa readers. Only use contemporary casual wording "
        "when the character is already casual. Keep serious, historical, formal, threatening, or narration lines serious."
    ),
    "us_2026": (
        "Slang adaptation: United States 2026. Use natural US English. Only use current casual phrasing when the character is already casual. "
        "Avoid meme-speak, preserve tone, and keep formal or historical speech formal."
    ),
    "jp_2026": (
        "Slang adaptation: Japan 2026. When appropriate, localize casual speech with modern Japanese youth/media flavor expressed naturally "
        "in the target language. Keep honorifics/social distance when meaningful and avoid forcing slang."
    ),
    "kr_2026": (
        "Slang adaptation: Korea 2026. When appropriate, write casual dialogue like modern Korean webtoon/K-culture speech. "
        "Preserve Korean respect levels, age/status nuance, and relationship tone."
    ),
    "cn_2026": (
        "Slang adaptation: China 2026. When appropriate, write casual dialogue like modern Chinese manhua/web culture speech. "
        "Preserve status, formality, and genre tone."
    ),
    "global_auto": (
        "Slang adaptation: global automatic. Adapt casual dialogue naturally to the target language and region when the source voice supports it. "
        "Use current, readable phrasing, preserve character voice, and avoid memes, catchphrases, or excessive slang."
    ),
}
SLANG_ADAPTATION_TARGET_LANGS = {
    "natural_br": "Portuguese (Brazil)",
    "br_2026": "Portuguese (Brazil)",
    "us_2026": "English (United States)",
    "jp_2026": "Japanese",
    "kr_2026": "Korean",
    "cn_2026": "Chinese (Simplified)",
}


def _normalize_slang_adaptation(value: str | None) -> str:
    key = (value or "auto").strip().lower().replace("-", "_")
    aliases = {
        "0": "off",
        "false": "off",
        "no": "off",
        "disabled": "off",
        "disable": "off",
        "off": "off",
        "1": "auto",
        "true": "auto",
        "yes": "auto",
        "enabled": "auto",
        "enable": "auto",
        "on": "auto",
        "faithful": "faithful_global",
        "faithful_western": "faithful_global",
        "western": "faithful_global",
        "fiel ao contexto ocidental": "faithful_global",
        "natural": "natural_br",
        "natural brasileiro": "natural_br",
        "natural brazilian": "natural_br",
        "brazil": "br_2026",
        "brasil": "br_2026",
        "usa": "us_2026",
        "united_states": "us_2026",
        "japan": "jp_2026",
        "korea": "kr_2026",
        "china": "cn_2026",
    }
    key = aliases.get(key, key)
    if key == "auto":
        return "auto"
    return key if key in SLANG_ADAPTATION_GUIDES else "auto"


def _auto_slang_adaptation_for_target(target_lang: str) -> str:
    target = (target_lang or "").strip().lower()
    if "brazil" in target or "brasil" in target or "portuguese (brazil" in target or target in {"pt-br", "pt_br"}:
        return "natural_br"
    if target.startswith("english") or "united states" in target or target in {"en", "en-us", "en_us"}:
        return "us_2026"
    if target.startswith("japanese") or target in {"ja", "jp"}:
        return "jp_2026"
    if target.startswith("korean") or target in {"ko", "kr"}:
        return "kr_2026"
    if target.startswith("chinese") or target in {"zh", "zh-cn", "zh_hans", "zh-hans"}:
        return "cn_2026"
    return "global_auto"


def _resolve_slang_adaptation(mode: str | None, target_lang: str) -> str:
    normalized = _normalize_slang_adaptation(mode)
    if normalized == "auto":
        return _auto_slang_adaptation_for_target(target_lang)
    return normalized


def _slang_adaptation_instruction(mode: str | None, target_lang: str) -> str:
    normalized = _resolve_slang_adaptation(mode, target_lang)
    guide = SLANG_ADAPTATION_GUIDES[normalized]
    target_locale = _target_lang_for_slang_adaptation(normalized, target_lang)
    return (
        f"{guide}\n"
        f"The final text must be written in {target_locale}. Do not add translator notes. "
        "Accuracy and character intent are more important than slang. "
        "When the source has slang, stutters, borrowed words, broken speech, or mixed-language expressions, adapt the intent naturally to the target locale. "
        "Do not insert slang where the source is neutral, ceremonial, old-fashioned, threatening, or serious."
    )


def _target_lang_for_slang_adaptation(mode: str | None, target_lang: str) -> str:
    normalized = mode if mode in SLANG_ADAPTATION_GUIDES else _resolve_slang_adaptation(mode, target_lang)
    return SLANG_ADAPTATION_TARGET_LANGS.get(normalized) or target_lang


def _translate_live_text(text: str, source_lang: str, target_lang: str, llm_model: str, adaptation_mode: str = "auto") -> str:
    cleaned = _merge_visual_lines_to_paragraphs(text)
    if not cleaned:
        return ""

    adaptation_mode = _resolve_slang_adaptation(adaptation_mode, target_lang)
    effective_target_lang = _target_lang_for_slang_adaptation(adaptation_mode, target_lang)
    cache_key = (source_lang or "Auto", effective_target_lang, adaptation_mode, cleaned)
    if cache_key in LIVE_TRANSLATION_CACHE:
        cached = LIVE_TRANSLATION_CACHE[cache_key]
        if not _is_bad_live_translation(cached):
            return cached
        LIVE_TRANSLATION_CACHE.pop(cache_key, None)

    source_hint = (
        "Infer the source language from the OCR text."
        if not source_lang or source_lang.lower() == "auto"
        else f"The source language is {source_lang}."
    )
    prompts = [f"""Translate this manga/comic speech bubble to {effective_target_lang}.
{source_hint}
{_slang_adaptation_instruction(adaptation_mode, effective_target_lang)}
{_translation_quality_instruction(effective_target_lang)}
Translate the actual meaning, not just word-by-word OCR fragments.
Treat visual line breaks as layout only. Translate complete phrases and sentences.
Do not translate each visual line as a separate word or sentence.
Respect punctuation, commas, periods, question marks, exclamation marks, and ellipses when joining text.
If the OCR repeats the same word/line because of recognition noise, keep the most complete single reading.
If the source has stutter, slang, mixed-language wording, or broken speech, adapt it naturally in the target language without duplicating words.
Preserve names, titles, ranks, numbers, and cause/effect.
Keep it concise enough for a speech bubble, but do not drop important meaning.
If the OCR is partially corrupted, translate only the confident readable content without inventing missing facts.
Keep paragraph breaks if they are present. Return only the translated text. No notes, no quotes.

OCR TEXT:
{cleaned}
""", f"""You are given OCR text from a manga speech bubble. Translate it to {effective_target_lang}.
{source_hint}
{_slang_adaptation_instruction(adaptation_mode, effective_target_lang)}
{_translation_quality_instruction(effective_target_lang)}
Do not ask for OCR. Do not explain. Do not mention policies or limitations.
Preserve the original meaning, names, titles, ranks, numbers, and tone.
Do not summarize, embellish, or add facts that are not in the OCR.
Collapse OCR repetition noise and translate stutters or slang as natural dialogue.
Do not treat each visual line break as a separate word; join lines into complete phrases with correct punctuation.
Return only the translated speech bubble text. Keep paragraph breaks if useful.

OCR:
<<<{cleaned}>>>
"""]
    model_name = llm_model.strip() or mt.LLM_MODEL
    result = ""
    for prompt in prompts:
        translated = mt.ollama(
            model_name,
            prompt,
            timeout=90,
            num_predict=320,
            temperature=0.15,
        )
        result = _postprocess_live_translation(translated, effective_target_lang)
        if not _translation_suspicious_for_source(cleaned, result, effective_target_lang):
            break
        result = ""
    if not result:
        result = _fallback_short_expression_translation(cleaned, effective_target_lang)

    LIVE_TRANSLATION_CACHE[cache_key] = result
    if len(LIVE_TRANSLATION_CACHE) > 1000:
        LIVE_TRANSLATION_CACHE.pop(next(iter(LIVE_TRANSLATION_CACHE)))
    return result


def _translate_live_text_batch(items: list[tuple[int, str]], source_lang: str, target_lang: str, llm_model: str, adaptation_mode: str = "auto") -> dict[int, str]:
    cleaned_items = []
    for idx, text in items:
        cleaned = _merge_visual_lines_to_paragraphs(text)
        if cleaned:
            cleaned_items.append((idx, cleaned))
    if not cleaned_items:
        return {}

    results: dict[int, str] = {}
    pending: list[tuple[int, str]] = []
    adaptation_mode = _resolve_slang_adaptation(adaptation_mode, target_lang)
    effective_target_lang = _target_lang_for_slang_adaptation(adaptation_mode, target_lang)
    for idx, text in cleaned_items:
        cache_key = (source_lang or "Auto", effective_target_lang, adaptation_mode, text)
        cached = LIVE_TRANSLATION_CACHE.get(cache_key)
        if cached and not _is_bad_live_translation(cached):
            results[idx] = cached
        else:
            pending.append((idx, text))

    if not pending:
        return results

    source_hint = (
        "Infer the source language from each OCR text."
        if not source_lang or source_lang.lower() == "auto"
        else f"The source language is {source_lang}."
    )
    payload = [{"idx": idx, "text": text} for idx, text in pending]
    prompt = f"""Translate these manga/comic speech bubbles to {effective_target_lang}.
{source_hint}
{_slang_adaptation_instruction(adaptation_mode, effective_target_lang)}
{_translation_quality_instruction(effective_target_lang)}
Translate for meaning and coherence first, then naturalness.
Treat visual line breaks as layout only. Translate complete phrases and sentences.
Do not translate each visual line as a separate word or sentence.
Respect punctuation, commas, periods, question marks, exclamation marks, and ellipses when joining text.
If OCR repeats the same word/line because of recognition noise, keep the most complete single reading.
If the source has stutter, slang, mixed-language wording, or broken speech, adapt it naturally in the target language without duplicating words.
Preserve names, titles, ranks, numbers, relationships, threats, jokes, and cause/effect.
Keep translations natural for speech bubbles, but do not remove meaning just to make the line shorter.
Preserve paragraph breaks when present.
The entries are in manga reading order and may be consecutive parts of the same page.
Use nearby entries only as context for pronouns, tone, and speaker intent.
Each entry must remain an independent translation of its own OCR text.
Do not merge entries, split entries, summarize, invent missing facts, or move meaning between bubbles.
If OCR is partially corrupted, translate the confident readable content and keep the result coherent.
Return ONLY a JSON array in the same order, using this schema:
[{{"idx": 1, "translation": "translated text"}}]

INPUT:
{json.dumps(payload, ensure_ascii=False)}
"""
    model_name = llm_model.strip() or mt.LLM_MODEL
    raw = mt.ollama(
        model_name,
        prompt,
        timeout=max(90, 45 + 20 * len(pending)),
        num_predict=max(320, 180 * len(pending)),
        temperature=0.15,
    )
    parsed = mt.parse_json_array(raw)
    pending_text_by_idx = dict(pending)
    for item in parsed:
        try:
            idx = int(item.get("idx"))
        except Exception:
            continue
        translation = _postprocess_live_translation(str(item.get("translation", "")), effective_target_lang)
        source_text = pending_text_by_idx.get(idx, "")
        if translation and not _translation_suspicious_for_source(source_text, translation, effective_target_lang):
            results[idx] = translation

    missing = [(idx, text) for idx, text in pending if idx not in results]
    if missing:
        print(f"     [translate batch fallback] {len(missing)} missing item(s)")
    for idx, text in missing:
        translation = _translate_live_text(text, source_lang, target_lang, llm_model, adaptation_mode)
        if not translation:
            translation = _fallback_short_expression_translation(text, effective_target_lang)
        if translation and not _translation_suspicious_for_source(text, translation, effective_target_lang):
            results[idx] = translation

    for idx, text in cleaned_items:
        translation = results.get(idx, "")
        if translation:
            _cache_put_limited(
                LIVE_TRANSLATION_CACHE,
                (source_lang or "Auto", effective_target_lang, adaptation_mode, text),
                translation,
                1000,
            )
    return results


def _clean_live_translation(raw: str) -> str:
    text = raw or ""
    text = re.sub(r"```[a-zA-Z0-9_-]*\s*", "", text)
    text = text.replace("```", "").replace("`", "")

    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip().strip("\"'")
        cleaned = re.sub(r"^(translation|tradução|traduccion|traducción|portuguese|português)\s*:\s*", "", cleaned, flags=re.I)
        lines.append(cleaned)

    compact = []
    previous_blank = False
    for line in lines:
        if not line:
            if compact and not previous_blank:
                compact.append("")
            previous_blank = True
            continue
        compact.append(line)
        previous_blank = False

    while compact and not compact[-1]:
        compact.pop()
    cleaned = _remove_duplicate_dialogue_lines("\n".join(compact)).strip()
    return _merge_clean_lines_to_paragraphs(cleaned)


def _is_bad_live_translation(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    if _has_prompt_echo_fragment(lowered):
        return True
    if _has_visual_failure_fragment(lowered):
        return True
    if _has_repeated_ngram_noise(lowered):
        return True
    words = re.findall(r"[A-Za-z0-9À-ÿ']+", lowered)
    if len(words) >= 6:
        repeated = Counter(words).most_common(1)[0]
        if len(repeated[0]) >= 3 and repeated[1] >= 4 and repeated[1] / max(1, len(words)) >= 0.38:
            return True
    normalized_lines = [_normalized_dialogue_line(line) for line in lowered.splitlines() if line.strip()]
    if len(normalized_lines) >= 3:
        counts = Counter(normalized_lines)
        if any(line and count >= 3 for line, count in counts.items()):
            return True
    return False


def _is_bad_bubble_ocr(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9']+", lowered)
    if not words:
        return True
    signal_chars = re.sub(r"[\W_]+", "", lowered, flags=re.UNICODE)
    if len(signal_chars) <= 2 and lowered not in {"no", "go", "ok", "yo", "ha", "ah", "eh"}:
        return True
    if len(words) == 1 and words[0] in {"manga", "bubble", "image", "text", "line", "lines", "visible"}:
        return True
    repeated = Counter(words).most_common(1)[0]
    if repeated[1] >= 3 and repeated[1] / max(1, len(words)) >= 0.45:
        return True
    if _has_prompt_echo_fragment(lowered):
        return True
    if _has_visual_failure_fragment(lowered):
        return True
    if _has_repeated_ngram_noise(lowered):
        return True
    blocked = (
        "no spaces",
        "markdown markdown",
        "json json",
        "html html",
        "css css",
        "cannot read",
        "discord",
        "scanlation",
        "scanlator",
        "read more",
        "more chapters",
        "chapter on",
        "chapter at",
        "follow us",
        "support us",
        "website",
        "watermark",
        "official site",
    )
    if any(fragment in lowered for fragment in blocked):
        return True
    punctuation = sum(1 for ch in lowered if ch in "{}[]<>`|")
    return punctuation > 5 and punctuation > len(lowered) * 0.08


def _ndjson(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


@app.post("/api/translate-image")
async def translate_web_image(
    file: UploadFile = File(...),
    source_lang: str = Form("Auto"),
    target_lang: str = Form("Portuguese (Brazil)"),
    font_path: str = Form(mt.DEFAULT_FONT_ALIAS),
    font_size: Optional[int] = Form(None),
    debug: bool = Form(False),
    llm_model: str = Form(""),
    llm_debug: bool = Form(False),
    fast_mode: bool = Form(True),
):
    """
    One-shot endpoint for browser extensions.
    Uploads a single web image, runs the translator, and returns the rendered URL.
    """
    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in mt.SUPPORTED_EXTENSIONS:
        ext = ".png"

    job_id = uuid.uuid4().hex[:12]
    meta = _read_job_meta(job_id)
    storage_name = meta.get("storage_name", job_id)
    upload_dir = UPLOADS_DIR / storage_name
    result_dir = RESULTS_DIR / storage_name
    upload_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"web_image{ext}"
    target = upload_dir / safe_name
    with open(target, "wb") as out:
        shutil.copyfileobj(file.file, out)

    mt.DEBUG_LLM = bool(llm_debug)
    stats = await asyncio.to_thread(
        mt.process_directory,
        input_dir=str(upload_dir),
        output_dir=str(result_dir),
        source_lang=source_lang,
        target_lang=target_lang,
        font_path=font_path,
        font_size=font_size,
        debug=debug,
        fast_mode=fast_mode,
        llm_model=llm_model.strip() or None,
        error_log_path=str(JOBS_DIR / f"{job_id}_errors.log"),
    )

    translated = result_dir / "web_image_translated.webp"
    if not translated.exists():
        raise HTTPException(500, "Translation finished but no output image was created")

    url = f"/files/results/{job_id}/{translated.name}"
    return {
        "ok": True,
        "job_id": job_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "url": url,
        "absolute_url": f"http://localhost:8000{url}",
        "stats": stats,
    }


@app.post("/api/translate-image-bubbles")
async def translate_web_image_bubbles(
    file: UploadFile = File(...),
    source_lang: str = Form("Auto"),
    target_lang: str = Form("Portuguese (Brazil)"),
    font_path: str = Form(mt.DEFAULT_FONT_ALIAS),
    font_size: Optional[int] = Form(None),
    debug: bool = Form(False),
    llm_model: str = Form(""),
    llm_debug: bool = Form(False),
    fast_mode: bool = Form(True),
    adaptation_mode: str = Form("auto"),
    slang_adaptation: bool = Form(True),
):
    """
    Browser-extension endpoint for live overlays.
    It detects/OCRs/translates bubbles, but does not inpaint or render a new image.
    """
    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in mt.SUPPORTED_EXTENSIONS:
        ext = ".png"

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOADS_DIR / job_id
    meta = _read_job_meta(job_id)
    storage_name = meta.get("storage_name", job_id)
    result_dir = RESULTS_DIR / storage_name
    upload_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    image_path = upload_dir / f"web_image{ext}"
    with open(image_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    mt.DEBUG_LLM = bool(llm_debug)
    bubbles = await asyncio.to_thread(
        mt.process_page,
        image_path=str(image_path),
        page_idx=1,
        manga_ctx=mt.MangaContext(),
        archive=mt.CharacterArchive(str(JOBS_DIR / f"{job_id}_characters.json")),
        output_path=str(result_dir / "web_image_translated.webp"),
        source_lang=source_lang,
        target_lang=target_lang,
        font_size=font_size,
        debug=debug,
        fast_mode=fast_mode,
        render_output=False,
        errors=mt.ErrorLog(str(JOBS_DIR / f"{job_id}_errors.log")),
    )

    payload = _bubble_response_payload(image_path, bubbles or [])
    if not payload["bubbles"]:
        raise HTTPException(422, "No readable manga bubbles found in this image")

    return {
        "ok": True,
        "mode": "bubble_overlay",
        "job_id": job_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        **payload,
    }


@app.post("/api/translate-image-bubbles-stream")
async def translate_web_image_bubbles_stream(
    request: Request,
    file: UploadFile = File(...),
    source_lang: str = Form("Auto"),
    target_lang: str = Form("Portuguese (Brazil)"),
    font_path: str = Form(mt.DEFAULT_FONT_ALIAS),
    font_size: Optional[int] = Form(None),
    debug: bool = Form(False),
    llm_model: str = Form(""),
    llm_debug: bool = Form(False),
    fast_mode: bool = Form(True),
    adaptation_mode: str = Form("auto"),
    slang_adaptation: bool = Form(True),
):
    """
    Streaming browser-extension endpoint.
    Sends detected bubble boxes first, then one translated bubble per line.
    """
    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in mt.SUPPORTED_EXTENSIONS:
        ext = ".png"

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"web_image{ext}"
    with open(image_path, "wb") as out:
        shutil.copyfileobj(file.file, out)
    image_key = _file_sha1(image_path)

    async def stream():
        tasks: list[asyncio.Task] = []
        try:
            mt.DEBUG_LLM = bool(llm_debug)
            requested_adaptation = "auto" if slang_adaptation else "off"
            if adaptation_mode and adaptation_mode != "auto":
                requested_adaptation = adaptation_mode
            adaptation_mode_normalized = _resolve_slang_adaptation(requested_adaptation, target_lang)
            result_cache_key = (image_key, source_lang or "Auto", target_lang, adaptation_mode_normalized, llm_model.strip() or mt.LLM_MODEL)
            cached_result = LIVE_IMAGE_RESULT_CACHE.get(result_cache_key)
            if cached_result:
                yield _ndjson({
                    "type": "detected",
                    "job_id": job_id,
                    "image_width": cached_result["image_width"],
                    "image_height": cached_result["image_height"],
                    "bubbles": cached_result["bubbles"],
                })
                for bubble in cached_result["bubbles"]:
                    yield _ndjson({
                        "type": "bubble",
                        "job_id": job_id,
                        "image_width": cached_result["image_width"],
                        "image_height": cached_result["image_height"],
                        "bubble": bubble,
                    })
                yield _ndjson({"type": "done", "job_id": job_id, "translated": len(cached_result["bubbles"]), "cached": True})
                return

            img_cv, bubbles = await asyncio.to_thread(_detect_text_bubbles_cached, image_path, image_key)

            if font_size:
                safe_font_size = max(6, min(72, int(font_size)))
                for bubble in bubbles:
                    bubble["font_size"] = safe_font_size

            detected = _bubble_response_payload(image_path, bubbles)
            yield _ndjson({
                "type": "detected",
                "job_id": job_id,
                **detected,
            })

            if not bubbles:
                yield _ndjson({"type": "done", "job_id": job_id, "translated": 0})
                return

            translated_count = 0
            translated_payloads: list[dict] = []
            pending_translate: list[tuple[int, dict]] = []
            ocr_sem = asyncio.Semaphore(WEB_OCR_CONCURRENCY)
            translate_sem = asyncio.Semaphore(WEB_TRANSLATION_CONCURRENCY)
            translation_tasks: list[asyncio.Task] = []

            async def run_ocr(index: int, bubble: dict):
                cache_key = (image_key, *_bubble_cache_box(bubble))
                cached_text = LIVE_OCR_CACHE.get(cache_key)
                if cached_text is not None:
                    return index, bubble, cached_text
                try:
                    async with ocr_sem:
                        text_value = await asyncio.to_thread(
                            _ocr_region_preserve_layout,
                            img_cv,
                            bubble,
                            index,
                        )
                except Exception as exc:
                    print(f"     [OCR web error] bubble {index}: {type(exc).__name__}: {exc}")
                    text_value = ""
                _cache_put_limited(LIVE_OCR_CACHE, cache_key, text_value)
                return index, bubble, text_value

            async def flush_translation_batch(batch: list[tuple[int, dict]]):
                nonlocal translated_count
                if not batch:
                    return []
                try:
                    translations = await asyncio.to_thread(
                        _translate_live_text_batch,
                        [(idx, bubble.get("text", "")) for idx, bubble in batch],
                        source_lang,
                        target_lang,
                        llm_model,
                        adaptation_mode_normalized,
                    )
                except Exception as exc:
                    print(f"     [translate web error] batch: {type(exc).__name__}: {exc}")
                    translations = {}
                events = []
                for idx, bubble in batch:
                    translation = translations.get(idx, "")
                    if not translation or _is_bad_live_translation(translation):
                        events.append(_ndjson({
                            "type": "discard",
                            "job_id": job_id,
                            "idx": idx,
                            "reason": "empty_translation",
                        }))
                        continue
                    bubble["translation"] = translation
                    translated_count += 1
                    payload = _bubble_response_payload(image_path, [bubble])["bubbles"][0]
                    payload["idx"] = idx
                    translated_payloads.append(payload)
                    events.append(_ndjson({
                        "type": "bubble",
                        "job_id": job_id,
                        "image_width": detected["image_width"],
                        "image_height": detected["image_height"],
                        "bubble": payload,
                    }))
                return events

            async def run_translation_batch(batch: list[tuple[int, dict]]):
                async with translate_sem:
                    async with LIVE_LLM_SEMAPHORE:
                        return await flush_translation_batch(batch)

            def queue_translation_batch(batch: list[tuple[int, dict]]):
                if batch:
                    translation_tasks.append(asyncio.create_task(run_translation_batch(batch)))

            async def yield_ready_translation_events():
                ready = [task for task in translation_tasks if task.done()]
                for task in ready:
                    translation_tasks.remove(task)
                    for event in await task:
                        yield event

            tasks = [
                asyncio.create_task(run_ocr(index, bubble))
                for index, bubble in enumerate(bubbles, start=1)
            ]
            for task in asyncio.as_completed(tasks):
                if await request.is_disconnected():
                    break
                index, bubble, text = await task
                bubble["text"] = text
                yield _ndjson({
                    "type": "ocr",
                    "job_id": job_id,
                    "idx": index,
                    "text": text,
                })

                if _is_bad_bubble_ocr(text):
                    yield _ndjson({
                        "type": "discard",
                        "job_id": job_id,
                        "idx": index,
                        "reason": "bad_ocr",
                    })
                    continue

                if text:
                    pending_translate.append((index, bubble))
                    if len(pending_translate) >= WEB_TRANSLATION_BATCH_SIZE:
                        if await request.is_disconnected():
                            break
                        batch = sorted(pending_translate, key=lambda item: item[0])
                        pending_translate = []
                        queue_translation_batch(batch)
                async for event in yield_ready_translation_events():
                    yield event

            if pending_translate and not await request.is_disconnected():
                batch = sorted(pending_translate, key=lambda item: item[0])
                queue_translation_batch(batch)

            for task in asyncio.as_completed(translation_tasks):
                if await request.is_disconnected():
                    break
                for event in await task:
                    yield event

            if translated_payloads:
                final_payload = {
                    "image_width": detected["image_width"],
                    "image_height": detected["image_height"],
                    "bubbles": sorted(translated_payloads, key=lambda bubble: int(bubble.get("idx", 0) or 0)),
                }
                _cache_put_limited(LIVE_IMAGE_RESULT_CACHE, result_cache_key, final_payload)

            yield _ndjson({"type": "done", "job_id": job_id, "translated": translated_count})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield _ndjson({
                "type": "error",
                "job_id": job_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in translation_tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if translation_tasks:
                await asyncio.gather(*translation_tasks, return_exceptions=True)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/translate-image-fast")
async def translate_web_image_fast(
    file: UploadFile = File(...),
    source_lang: str = Form("Auto"),
    target_lang: str = Form("Portuguese (Brazil)"),
    llm_model: str = Form(""),
    adaptation_mode: str = Form("auto"),
    slang_adaptation: bool = Form(True),
):
    """
    Fast browser-extension path: OCR the whole visible image and return text.
    This avoids detector/inpainting/render downloads and updates the web page quickly.
    """
    def looks_like_bad_ocr(text: str) -> bool:
        lower = text.lower()
        suspicious = ("markdown markdown", '"price"', "'price'", "currency", "usd", "{", "}", "[", "]")
        if sum(1 for token in suspicious if token in lower) >= 3:
            return True
        braces = text.count("{") + text.count("}") + text.count("[") + text.count("]")
        quotes = text.count('"') + text.count("'")
        return braces > 8 or quotes > max(24, len(text) // 8)

    ext = Path(file.filename or "").suffix.lower() or ".png"
    if ext not in mt.SUPPORTED_EXTENSIONS:
        ext = ".png"

    job_id = uuid.uuid4().hex[:12]
    upload_dir = UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    image_path = upload_dir / f"web_image{ext}"
    with open(image_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    def run_fast_translation():
        requested_adaptation = "auto" if slang_adaptation else "off"
        if adaptation_mode and adaptation_mode != "auto":
            requested_adaptation = adaptation_mode
        effective_target_lang = _target_lang_for_slang_adaptation(requested_adaptation, target_lang)
        adaptation_instruction = _slang_adaptation_instruction(requested_adaptation, effective_target_lang)
        ocr_prompt = (
            "Extract only visible manga/comic dialogue and narration from this image. "
            "Ignore website UI, ads, prices, metadata, JSON, markdown, and hidden text. "
            "Preserve line breaks and reading order. Return plain text only."
        )
        raw_text = mt.ollama(
            "glm-ocr:latest",
            ocr_prompt,
            str(image_path),
            timeout=120,
            num_predict=1200,
            temperature=0.0,
        )
        source_text = mt.clean_text(raw_text)
        source_hint = (
            "Infer the source language from the image/text."
            if not source_lang or source_lang.lower() == "auto"
            else f"The source language is {source_lang}."
        )

        previous_model = mt.LLM_MODEL
        if llm_model.strip():
            mt.LLM_MODEL = llm_model.strip()

        if not source_text or looks_like_bad_ocr(source_text):
            direct_prompt = f"""Look at this manga/comic screenshot and translate only the visible dialogue and narration to {effective_target_lang}.
{source_hint}
{adaptation_instruction}
Ignore website UI, ads, prices, metadata, JSON, markdown, and hidden text.
Return only the translated manga/comic text. Preserve line breaks when useful."""
            try:
                direct_translation = mt.ollama(
                    mt.LLM_MODEL,
                    direct_prompt,
                    str(image_path),
                    timeout=120,
                    num_predict=1200,
                    temperature=0.2,
                )
            finally:
                mt.LLM_MODEL = previous_model
            cleaned_direct = mt.clean_text(direct_translation)
            return {
                "source_text": "[vision direct translation]",
                "translation": cleaned_direct,
            }

        source_hint = (
            "Infer the source language from the OCR text."
            if not source_lang or source_lang.lower() == "auto"
            else f"The source language is {source_lang}."
        )
        translate_prompt = f"""Translate this manga/comic text to {effective_target_lang}.
{source_hint}
{adaptation_instruction}
Keep the same line breaks when possible. Make it natural, concise, and suitable for speech bubbles.
Return only the translated text.

TEXT:
{source_text}
"""
        try:
            translation = mt.ollama(
                mt.LLM_MODEL,
                translate_prompt,
                timeout=120,
                num_predict=1200,
                temperature=0.2,
            )
        finally:
            mt.LLM_MODEL = previous_model
        return {"source_text": source_text, "translation": mt.clean_text(translation)}

    result = await asyncio.to_thread(run_fast_translation)
    if not result["source_text"]:
        raise HTTPException(422, "No readable text found in this image")
    if not result["translation"]:
        raise HTTPException(500, "OCR succeeded but translation returned empty text")

    return {
        "ok": True,
        "mode": "text_overlay",
        "job_id": job_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        **result,
    }


# ─── запуск перевода и WebSocket прогресс ────────────────────────────────────

@app.websocket("/ws/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str):
    """
    Открывается клиентом сразу после upload.
    Клиент шлёт {"action": "start"} — запускаем перевод.
    Сервер шлёт события {type: "start"|"page_done"|"finish"|"error"|"log"}.
    """
    await websocket.accept()
    if job_id not in JOBS:
        meta = _read_job_meta(job_id)
        original_pages = _job_original_pages(job_id)
        if not original_pages:
            await websocket.send_json({"type": "error", "message": "Unknown job_id"})
            await websocket.close()
            return
        JOBS[job_id] = {
            "status": meta.get("status", "ready"),
            "config": meta.get("config", {}),
            "storage_name": meta.get("storage_name", job_id),
            "total_pages": meta.get("total_pages") or len(original_pages),
            "total": meta.get("total_pages") or len(original_pages),
            "completed": meta.get("completed", 0),
            "pages": [],
            "stats": None,
            "queue": asyncio.Queue(),
        }

    job = JOBS[job_id]
    loop = asyncio.get_running_loop()

    # Коллбэки бегают в синхронном потоке (process_directory блокирующий) —
    # нужно перебрасывать события в asyncio через call_soon_threadsafe
    def emit(payload: dict):
        loop.call_soon_threadsafe(job["queue"].put_nowait, payload)

    def on_start(total):
        job["status"] = "running"
        _write_job_meta(job_id, job)
        emit({"type": "start", "total": total})

    def on_page_done(page_idx, total, filename, output_path, bubbles, elapsed):
        job["completed"] = page_idx
        _write_job_meta(job_id, job)
        # Превращаем абсолютный путь в URL для браузера
        try:
            rel = Path(output_path).resolve().relative_to(BASE_DIR.resolve())
            url = f"/files/{rel.as_posix()}"
        except Exception:
            url = None
        # Минимальное представление баблов для редактора
        page_data = {
            "page": page_idx,
            "filename": filename,
            "url": url,
            "elapsed": elapsed,
            "bubbles": [
                {
                    "idx": i + 1,
                    "x": b.get("x"), "y": b.get("y"),
                    "w": b.get("width"), "h": b.get("height"),
                    "text": b.get("text", ""),
                    "translation": b.get("translation", ""),
                    "speaker": b.get("speaker", "unknown"),
                    "gender": b.get("gender", "unknown"),
                    "font_path": b.get("font_path"),    # per-bubble override (None = use default)
                    "font_size": b.get("font_size"),    # per-bubble override (None = auto-fit)
                    "render_x": b.get("render_x", b.get("overlay_x")),
                    "render_y": b.get("render_y", b.get("overlay_y")),
                    "render_w": b.get("render_width", b.get("overlay_w")),
                    "render_h": b.get("render_height", b.get("overlay_h")),
                }
                for i, b in enumerate(bubbles)
            ],
        }
        job["pages"].append(page_data)
        # Сохраняем по job_id, чтобы редактор мог потом править
        (JOBS_DIR / f"{job_id}.json").write_text(
            json.dumps(job["pages"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_job_meta(job_id, job)
        emit({"type": "page_done", **page_data})

    def on_finish(stats):
        job["status"] = "done"
        job["stats"] = stats
        _write_job_meta(job_id, job)
        emit({"type": "finish", "stats": stats})

    def on_stage(page_idx, stage_key):
        emit({"type": "stage", "page": page_idx, "stage_key": stage_key})

    async def run_job():
        """Запускает синхронный перевод в отдельном потоке."""
        cfg = job["config"]
        storage_name = job.get("storage_name", job_id)
        upload_dir = UPLOADS_DIR / storage_name
        result_dir = RESULTS_DIR / storage_name
        if not upload_dir.exists():
            upload_dir = UPLOADS_DIR / job_id
        result_dir.mkdir(parents=True, exist_ok=True)
        job["pages"] = []

        # Включаем подробный лог LLM для этого джоба если запросили
        mt.DEBUG_LLM = bool(cfg.get("llm_debug"))
        if mt.DEBUG_LLM:
            print("\n*** VERBOSE LLM LOGGING ENABLED — every prompt/response will be printed ***\n")

        await asyncio.to_thread(
            mt.process_directory,
            input_dir=str(upload_dir),
            output_dir=str(result_dir),
            source_lang=cfg.get("source_lang", "Auto"),
            target_lang=cfg["target_lang"],
            font_path=cfg["font_path"],
            debug=cfg["debug"],
            fast_mode=cfg.get("fast_mode", False),
            llm_model=cfg.get("llm_model"),
            error_log_path=str(JOBS_DIR / f"{job_id}_errors.log"),
            on_start=on_start,
            on_page_done=on_page_done,
            on_finish=on_finish,
            on_stage=on_stage,
        )

    runner_task: Optional[asyncio.Task] = None
    try:
        while True:
            # Ждём либо команды от клиента, либо событий из очереди
            recv_task = asyncio.create_task(websocket.receive_json())
            queue_task = asyncio.create_task(job["queue"].get())
            done, pending = await asyncio.wait(
                {recv_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if recv_task in done:
                try:
                    msg = recv_task.result()
                except Exception:
                    break
                if msg.get("action") == "start" and job["status"] == "ready":
                    runner_task = asyncio.create_task(run_job())
                elif msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})

            if queue_task in done:
                event = queue_task.result()
                await websocket.send_json(event)
                if event.get("type") == "finish":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if runner_task and not runner_task.done():
            # Даём джобу довыполниться в фоне — он сам зачистит state
            pass


# ─── редактор: правка переводов ──────────────────────────────────────────────

@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    """Возвращает все страницы джоба с баблами для редактора."""
    job_file = JOBS_DIR / f"{job_id}.json"
    if job_file.exists():
        return json.loads(job_file.read_text(encoding="utf-8"))
    original_pages = _job_original_pages(job_id)
    if original_pages:
        return original_pages
    raise HTTPException(404, "Job not found")


@app.get("/api/jobs")
async def list_jobs():
    jobs = []
    ids = set()
    for path in JOBS_DIR.glob("*_meta.json"):
        ids.add(path.name[:-10])
    for path in JOBS_DIR.glob("*.json"):
        if path.name.endswith("_meta.json"):
            continue
        ids.add(path.stem)

    for job_id in sorted(ids):
        meta = _read_job_meta(job_id)
        pages_file = JOBS_DIR / f"{job_id}.json"
        page_count = 0
        if pages_file.exists():
            try:
                page_count = len(json.loads(pages_file.read_text(encoding="utf-8")))
            except Exception:
                page_count = 0
        cfg = meta.get("config", {})
        jobs.append({
            "job_id": job_id,
            "status": meta.get("status", "saved" if page_count else "ready"),
            "completed": meta.get("completed", page_count),
            "total_pages": meta.get("total_pages", page_count),
            "storage_name": meta.get("storage_name", job_id),
            "work_title": cfg.get("work_title") or "",
            "chapter_number": cfg.get("chapter_number") or "",
            "source_lang_code": cfg.get("source_lang_code") or "",
            "target_lang_code": cfg.get("target_lang_code") or "",
            "target_lang": cfg.get("target_lang") or "",
            "pages_saved": page_count,
        })
    jobs.sort(key=lambda j: (_job_meta_path(j["job_id"]).stat().st_mtime if _job_meta_path(j["job_id"]).exists() else 0), reverse=True)
    return {"jobs": jobs}


@app.post("/api/job/{job_id}/page/{page_idx}/render")
async def re_render_page(job_id: str, page_idx: int, payload: dict):
    """
    Перерисовывает страницу с обновлёнными переводами.
    payload: {"bubbles": [{"idx": 1, "translation": "новый перевод"}, ...]}
    """
    job_file = JOBS_DIR / f"{job_id}.json"
    if not job_file.exists():
        raise HTTPException(404, "Job not found")

    pages = json.loads(job_file.read_text(encoding="utf-8"))
    page = next((p for p in pages if p["page"] == page_idx), None)
    if not page:
        raise HTTPException(404, "Page not found")

    # Применяем обновления баблов (translation, font_path, font_size).
    # Только указанные в payload поля затрагиваются — остальные сохраняются.
    updates = {b["idx"]: b for b in payload.get("bubbles", []) if "idx" in b}
    for b in page["bubbles"]:
        if b["idx"] in updates:
            u = updates[b["idx"]]
            if "translation" in u:
                b["translation"] = u.get("translation") or ""
            if "font_path" in u:
                # None или пустая строка — сбрасываем override
                b["font_path"] = u["font_path"] if u["font_path"] else None
            if "font_size" in u:
                b["font_size"] = u["font_size"] if u["font_size"] else None

    # Перерисовываем страницу
    meta = _read_job_meta(job_id)
    storage_name = meta.get("storage_name", job_id)
    upload_dir = UPLOADS_DIR / storage_name
    result_dir = RESULTS_DIR / storage_name
    if not upload_dir.exists():
        upload_dir = UPLOADS_DIR / job_id
    result_dir.mkdir(parents=True, exist_ok=True)
    src_path = upload_dir / page["filename"]

    import cv2
    import numpy as np
    img_cv = cv2.imread(str(src_path))
    if img_cv is None:
        img_cv = cv2.imdecode(np.fromfile(str(src_path), dtype=np.uint8),
                              cv2.IMREAD_COLOR)

    # Восстанавливаем структуру bubbles в формате draw_results
    bubbles_for_draw = [
        {
            "x": b["x"], "y": b["y"],
            "width": b["w"], "height": b["h"],
            "text": b.get("text", ""),
            "translation": b.get("translation", ""),
            "class": "text_bubble",   # для цвета рамки, влияет только в debug
            "speaker": b.get("speaker", ""),
            "gender": b.get("gender", ""),
            # Per-bubble overrides — могут быть None
            "font_path": b.get("font_path"),
            "font_size": b.get("font_size"),
            "render_x": b.get("render_x"),
            "render_y": b.get("render_y"),
            "render_width": b.get("render_w"),
            "render_height": b.get("render_h"),
        }
        for b in page["bubbles"]
    ]
    annotated = mt.draw_results(img_cv, bubbles_for_draw, debug=False)

    out_path = result_dir / f"{Path(page['filename']).stem}_translated.webp"
    mt.save_output_image(str(out_path), annotated)

    # Сохраняем обновлённые баблы обратно
    job_file.write_text(json.dumps(pages, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    return {"ok": True, "url": f"/files/results/{storage_name}/{out_path.name}"}


# ─── архив персонажей ─────────────────────────────────────────────────────────

@app.get("/api/job/{job_id}/export")
async def export_job(job_id: str, fmt: str = "zip"):
    """
    Собирает все переведённые страницы джоба в архив (zip или cbz).
    fmt: 'zip' (по умолчанию) или 'cbz' (тот же zip с расширением .cbz —
    стандарт для манги/комиксов, открывается ридерами вроде CDisplayEx).
    """
    if fmt not in ("zip", "cbz"):
        raise HTTPException(400, "fmt must be 'zip' or 'cbz'")

    job_file = JOBS_DIR / f"{job_id}.json"
    if not job_file.exists():
        raise HTTPException(404, "Job not found")

    pages = json.loads(job_file.read_text(encoding="utf-8"))
    pages_sorted = sorted(pages, key=lambda p: p["page"])
    meta = _read_job_meta(job_id)
    storage_name = meta.get("storage_name", job_id)
    result_dir = RESULTS_DIR / storage_name
    if not result_dir.exists():
        result_dir = RESULTS_DIR / job_id

    if not result_dir.exists() or not any(result_dir.iterdir()):
        raise HTTPException(404, "No rendered pages found")

    # Используем in-memory буфер; для главы из 50-100 страниц это ~20-50MB
    import io
    import zipfile

    buf = io.BytesIO()
    pad = len(str(len(pages_sorted)))   # для 100 страниц → 3-значное паддинг
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in pages_sorted:
            # Имя файла в архиве: 001_page.png, 002_page.png, ...
            # Ридеры манги сортируют именно так
            src_name = Path(p["filename"]).stem
            src_path = result_dir / f"{src_name}_translated.webp"
            if not src_path.exists():
                legacy_path = result_dir / f"{src_name}_translated.png"
                if legacy_path.exists():
                    src_path = legacy_path
            if not src_path.exists():
                continue
            arc_name = f"{p['page']:0{pad}d}_{src_name}{src_path.suffix.lower()}"
            zf.write(src_path, arcname=arc_name)

    buf.seek(0)
    content = buf.getvalue()
    if not content:
        raise HTTPException(404, "No translated pages in this job")

    # Имя файла для скачивания
    cfg = meta.get("config", {})
    name_bits = [_safe_slug(cfg.get("work_title") or "translation"), _safe_slug(cfg.get("chapter_number") or job_id[:8], "chapter"), _safe_slug(cfg.get("target_lang_code") or "", "")]
    filename = "_".join(bit for bit in name_bits if bit) + f".{fmt}"
    media_type = "application/zip" if fmt == "zip" else "application/vnd.comicbook+zip"

    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


@app.get("/api/characters")
async def get_characters():
    """Возвращает содержимое characters.json."""
    path = Path("characters.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@app.put("/api/characters")
async def save_characters(data: dict):
    """Сохраняет characters.json после редактирования."""
    Path("characters.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "count": len(data)}


@app.delete("/api/characters")
async def clear_characters():
    """Очищает весь архив персонажей."""
    path = Path("characters.json")
    if path.exists():
        path.write_text("{}", encoding="utf-8")
    return {"ok": True}


@app.delete("/api/characters/{char_id}")
async def delete_character(char_id: str):
    """Удаляет одного персонажа из архива."""
    path = Path("characters.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if char_id not in data:
        raise HTTPException(404, "Character not found")
    del data[char_id]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
