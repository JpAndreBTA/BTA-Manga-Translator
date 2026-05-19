# BTA MangaTranslate extension

This Chrome extension sends manga/comic images from the current web page to the local BTA MangaTranslate server at `http://localhost:8000`, then replaces the page image with the translated render.

## Load locally

1. Start BTA MangaTranslate with `run.bat` from the project root.
2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Click Load unpacked and select this `chrome_extension` folder.
5. Open a manga page, click the BTA MangaTranslate extension, choose languages, then click Translate Visible Images.

Hovering a large image also shows a Translate Manga button for translating a single image.
