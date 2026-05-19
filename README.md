# BTA MangaTranslate

[![License: Non-Commercial](https://img.shields.io/badge/License-Non--Commercial-red.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Local LLM](https://img.shields.io/badge/LLM-Ollama-black.svg)](https://ollama.com/)

**BTA MangaTranslate** is a local manga and comic translation workstation. It detects speech bubbles, reads OCR text, translates dialogue with local Ollama models, removes original lettering with inpainting, renders translated text back into the image, and lets you edit or export the result from a modern backend UI.

It also includes a Chrome extension that can translate manga images directly on reading websites using the same local backend.

> Runs locally. No cloud API keys are required.

## Contents

- [Highlights](#highlights)
- [How It Works](#how-it-works)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Backend Web UI](#backend-web-ui)
- [Chrome Extension](#chrome-extension)
- [Languages](#languages)
- [Configuration](#configuration)
- [Environment Flags](#environment-flags)
- [API Overview](#api-overview)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)

## Highlights

| Feature | Status |
|---|---:|
| Multiple image upload for full chapters | Yes |
| Bubble detection with RT-DETRv2 | Yes |
| OCR through local Ollama models | Yes |
| Source and target language selection | Yes |
| Batch translation with page context | Yes |
| Character archive across pages | Yes |
| Intelligent inpaint rendering | Yes |
| Per-bubble text sizing and layout metadata | Yes |
| Visual editor with re-render | Yes |
| ZIP and CBZ chapter export | Yes |
| Chrome extension live overlay translation | Yes |
| Auto-translate toggle with cancellation | Yes |
| Tab close cancellation for extension jobs | Yes |
| Local-first privacy model | Yes |

<details>
<summary><strong>What makes it different?</strong></summary>

Most manga translators process each bubble in isolation. BTA MangaTranslate keeps chapter-level context:

- A **character archive** remembers recurring characters, names, genders, and descriptions.
- A **page context** helps the LLM translate short lines with the surrounding scene in mind.
- OCR, translation, inpaint, and rendering metadata are preserved so the editor can re-render individual pages.
- The Chrome extension uses streamed backend responses so visible text can appear progressively.

</details>

## How It Works

```text
Image or chapter pages
  |
  |-- Bubble and text-region detection
  |-- OCR per visible text region
  |-- Optional page and character analysis
  |-- Batch translation with source/target language controls
  |-- Original text removal with anime-big-lama inpaint
  |-- Translated text rendering with adaptive font sizing
  |-- Web editor, image download, ZIP export, or CBZ export
```

<details>
<summary><strong>Pipeline details</strong></summary>

- **Detection:** RT-DETRv2-based comic bubble detection from Hugging Face weights.
- **OCR:** Local OCR prompts sent to Ollama, with crop preprocessing for manga text.
- **Translation:** Local LLM prompts with source language, target language, speaker hints, page context, and nearby lines.
- **Inpaint:** anime-big-lama removes the original text before rendering.
- **Rendering:** PIL draws translated text using adaptive wrapping, contrast-aware colors, bubble shape hints, and font fitting.
- **Editor:** Saved job data can be reopened, edited, and re-rendered without re-uploading the chapter.

</details>

## Requirements

- Windows 10/11, Linux, or macOS.
- Python 3.10 or newer. The included launch scripts can install a portable Python automatically.
- [Ollama](https://ollama.com/) running locally at `http://localhost:11434`.
- At least one vision-capable Ollama model.
- Recommended OCR model: `glm-ocr`.
- GPU recommended for fast inpaint and detection. CPU works, but is slower.

Recommended Ollama models:

```bash
ollama pull gemma3:4b
ollama pull glm-ocr
```

Stronger but heavier options:

```bash
ollama pull gemma3:12b
ollama pull llava:13b
ollama pull qwen2.5vl:7b
```

## Quick Start

### Windows

```bat
run.bat
```

The launcher prepares the local Python environment, installs dependencies, checks Ollama, and opens:

```text
http://localhost:8000/
```

### Linux and macOS

```bash
chmod +x run.sh
./run.sh
```

### Manual Python install

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python setup.py
```

On Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
```

<details>
<summary><strong>CUDA vs CPU dependencies</strong></summary>

`requirements.txt` installs the default PyTorch package first. On startup,
`setup.py` checks the device:

- NVIDIA GPU detected through `nvidia-smi`: the launcher installs/reloads the
  CUDA 12.4 PyTorch wheels automatically.
- No NVIDIA GPU detected: the project keeps the default CPU-compatible PyTorch
  install and runs Python models on CPU.

Advanced overrides:

```bash
BTA_FORCE_CPU=1      # force CPU even when CUDA is available
BTA_CUDA_FP16=0      # keep CUDA but disable fp16 acceleration
```

</details>

## Backend Web UI

Open the backend at:

```text
http://localhost:8000/
```

The backend UI includes:

- **Translate:** Upload one or many manga pages, select source and target language, choose model, font, debug options, and fast mode.
- **Editor Visual:** Reopen translated pages, edit bubble text, adjust font options, and re-render.
- **Characters:** View, edit, save, or clear the chapter character archive.
- **Export:** Download translated pages as individual images, ZIP, or CBZ.
- **Modern BTA layout:** Dark sidebar, drag-and-drop upload zone, inpaint status, BTA Studio link, and donation button.

<details>
<summary><strong>Batch translation flow</strong></summary>

1. Drag chapter pages into the upload area.
2. Pick **Source language** or leave it on **Auto detect**.
3. Pick **Translation language**.
4. Select the Vision/LLM model from Ollama.
5. Enable or disable debug boxes, verbose LLM logs, and fast mode.
6. Wait for live WebSocket progress.
7. Edit pages if needed.
8. Export ZIP or CBZ.

</details>

## Chrome Extension

The `chrome_extension/` folder contains a local Chrome extension that talks to the backend.

### Load it locally

1. Start the backend with `run.bat`, `run.sh`, or `python setup.py`.
2. Open `chrome://extensions`.
3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select the `chrome_extension` folder.
6. Open a manga reader page and use the BTA MangaTranslate popup.

### Extension features

- Translate visible images on the current page.
- Translate a single hovered manga image.
- Auto-translate newly loaded chapter images.
- Stop and resume auto-translation from the toggle.
- Cancel backend work when the tab is closed.
- Keep auto-translation alive when navigating chapters inside the same tab.
- Render translated text as overlays using bubble-aware shape, width, and font sizing.
- Link to GitHub, BTA Studio, and donation support from the popup.

## Languages

The backend supports a broad selectable language list for both **Source language** and **Translation language**.

Source language can be set to **Auto detect**. Target language must be explicit.

Included options cover common manga translation targets such as:

```text
English, Portuguese, Portuguese (Brazil), Spanish, French, German,
Japanese, Korean, Chinese, Chinese (Simplified), Chinese (Traditional),
Russian, Italian, Arabic, Hindi, Indonesian, Thai, Vietnamese,
Polish, Turkish, Ukrainian, Swedish, Dutch, and many more.
```

The actual quality depends on the selected Ollama model.

## Configuration

Browser UI settings are stored in `localStorage`.

Generated backend data is stored locally:

| Path | Purpose |
|---|---|
| `web_data/` | Uploaded pages, translated outputs, job metadata |
| `characters.json` | Main character archive |
| `models/huggingface/` | Project-local Hugging Face cache configured by `setup.py` |
| `errors.log` | Translation and processing issues |

Optional Hugging Face token locations:

```text
HF_TOKEN environment variable
HUGGINGFACE_HUB_TOKEN environment variable
.env
.env.local
huggingface_token.txt
```

## Environment Flags

You can tune backend behavior with environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `BTA_PORT` | `8000` | Backend port used by the launcher |
| `BTA_WEB_OCR_CONCURRENCY` | `2` | Number of parallel OCR jobs for streamed extension translation |
| `BTA_WEB_TRANSLATION_BATCH` | `4` | Number of OCR items grouped per translation batch |
| `BTA_WEB_CACHE_LIMIT` | `240` | In-memory cache limit for detection and translation data |
| `BTA_WEB_SPLIT_TEXT_GROUPS` | `1` | Split large detected text groups by visual gaps |
| `BTA_WEB_SPLIT_VISUAL_TEXT` | `0` | Force visual splitting for speech-bubble text |

Example on PowerShell:

```powershell
$env:BTA_WEB_OCR_CONCURRENCY="3"
python setup.py
```

## API Overview

The backend is a FastAPI application. Main routes:

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Backend web UI |
| `/api/models` | GET | List usable Ollama models |
| `/api/upload` | POST | Create a chapter translation job |
| `/ws/{job_id}` | WebSocket | Live job progress |
| `/api/job/{job_id}` | GET | Load job metadata and pages |
| `/api/job/{job_id}/page/{page_idx}/render` | POST | Re-render one edited page |
| `/api/job/{job_id}/export?fmt=zip` | GET | Export translated chapter as ZIP |
| `/api/job/{job_id}/export?fmt=cbz` | GET | Export translated chapter as CBZ |
| `/api/characters` | GET/PUT/DELETE | Read, save, or clear character archive |
| `/api/translate-image-bubbles-stream` | POST | Stream OCR and overlay translations for the extension |
| `/api/translate-image-fast` | POST | Fast visible-image translation path |

<details>
<summary><strong>Extension endpoints</strong></summary>

The extension primarily uses:

- `/api/translate-image-bubbles-stream` for progressive OCR and translated bubble overlays.
- `/api/translate-image-bubbles` for one-shot bubble payloads.
- `/api/translate-image-fast` for a faster whole-image fallback path.
- `/api/models` to populate model choices.

</details>

## Project Structure

```text
MangaTranslate/
  web.py                       FastAPI backend and extension API
  web_ui.html                  Backend web interface
  manga_translator.py          OCR, translation, inpaint, rendering pipeline
  setup.py                     Local launcher and environment checks
  requirements.txt             Python dependencies
  run.bat                      Windows portable launcher
  run.sh                       Linux/macOS launcher
  chrome_extension/            Chrome extension
```

## Troubleshooting

<details>
<summary><strong>Ollama is not detected</strong></summary>

Make sure Ollama is installed and running:

```bash
ollama list
```

Then pull at least one vision model and the OCR model:

```bash
ollama pull gemma3:4b
ollama pull glm-ocr
```

</details>

<details>
<summary><strong>Translations are empty or strange</strong></summary>

Try another model. Some modified or abliterated model builds have broken vision or chat templates. Regular `gemma3` and common vision models are usually more reliable.

Enable **Verbose LLM logging** in the backend UI to inspect prompts and responses in the server console.

</details>

<details>
<summary><strong>Inpaint is slow</strong></summary>

Use a GPU-enabled PyTorch install when possible. The launcher detects NVIDIA GPUs and upgrades PyTorch to the CUDA wheel automatically; machines without CUDA stay on CPU.

Fast mode can reduce LLM calls, but inpaint still depends on your hardware.

</details>

<details>
<summary><strong>The extension does not translate the page</strong></summary>

Check that:

- The backend is running at `http://localhost:8000/`.
- The extension has been loaded from the local `chrome_extension/` folder.
- The current page contains normal image elements, not a protected canvas-only reader.
- Browser console errors are not blocked by the site Content Security Policy.

</details>

<details>
<summary><strong>Text size or line wrapping looks wrong</strong></summary>

Use the visual editor to adjust individual bubbles and re-render. The renderer uses OCR-derived layout hints, but very stylized lettering, vertical text, or dense credits pages can still need manual cleanup.

</details>

## Privacy

BTA MangaTranslate is local-first:

- Uploaded pages stay on your machine.
- Translation calls go to local Ollama at `localhost:11434`.
- The backend runs on `localhost:8000` unless you expose it yourself.

Network access is used for first-time dependency and model downloads from Python/PyPI/PyTorch/Hugging Face/Ollama sources.

## Responsible Use

BTA MangaTranslate is provided as a local personal tool. You are responsible for
the material you translate, store, share, publish, or redistribute with it.
Use it only for content you own, have purchased, or have permission to process,
and do not use it to bypass copyright, licensing, or distribution rights.

The authors and contributors are not responsible for improper, illegal, or
unauthorized use of the tool or for third-party content processed by users.

## Credits

BTA MangaTranslate builds on excellent open-source work:

- [Ollama](https://ollama.com/) for local model serving.
- [PyTorch](https://pytorch.org/) for model inference.
- [Transformers](https://github.com/huggingface/transformers) for RT-DETRv2 loading.
- [Hugging Face Hub](https://huggingface.co/) for model downloads.
- [anime-big-lama](https://huggingface.co/df1412/anime-big-lama) for manga-style inpainting.
- [RT-DETR](https://github.com/lyuwenyu/RT-DETR) and comic bubble detection weights for speech bubble detection.
- [FastAPI](https://fastapi.tiangolo.com/) for the backend.

## Support

- GitHub: [JpAndreBTA/BTA-Manga-Translator](https://github.com/JpAndreBTA/BTA-Manga-Translator)
- Donate: [PayPal donation page](https://www.paypal.com/donate/?hosted_button_id=H33M9F9S2MZ38)

## License

BTA MangaTranslate is free for non-commercial use only. Commercial use, resale,
paid hosting, paid service integration, and monetized redistribution require
prior written permission from BTA Studio. See [LICENSE](LICENSE).
