const SERVER = "http://localhost:8000";
const BUBBLE_PROGRESS_FLUSH_SIZE = 5;
const tabControllers = new Map();
const BTA_BACKEND_HOSTNAMES = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
const BTA_BACKEND_PORTS = new Set(["", "8000", "8001", "8002", "8003", "8004", "8005", "8006", "8007", "8008", "8009", "8010", "8011", "8012", "8013", "8014", "8015", "8016", "8017", "8018", "8019", "8020"]);

function isBackendUrl(url = "") {
  try {
    const parsed = new URL(url);
    return BTA_BACKEND_HOSTNAMES.has(parsed.hostname) && BTA_BACKEND_PORTS.has(parsed.port);
  } catch {
    return false;
  }
}

async function blobToDataUrl(blob) {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return `data:${blob.type || "image/png"};base64,${btoa(binary)}`;
}

function fontPathFromFamily(family) {
  const fonts = {
    "Anime Ace": "animeace2_bld.ttf",
    "Anime Sans": "arialbd.ttf",
    "Comic Bold": "C:/Windows/Fonts/comicbd.ttf",
    "Impact": "C:/Windows/Fonts/impact.ttf",
    "Marker": "C:/Windows/Fonts/comicz.ttf"
  };
  return fonts[family] || fonts["Anime Ace"];
}

function filenameFromUrl(url) {
  try {
    const path = new URL(url).pathname;
    const name = path.split("/").pop() || "web_image.png";
    return /\.[a-z0-9]{2,5}$/i.test(name) ? name : "web_image.png";
  } catch {
    return "web_image.png";
  }
}

function sendProgress(sender, payload) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return;
  try {
    const pending = chrome.tabs.sendMessage(tabId, payload);
    if (pending && typeof pending.catch === "function") pending.catch(() => {});
  } catch {
    // The tab may navigate while a stream is still running.
  }
}

function rememberTabController(sender, controller) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return () => {};
  const controllers = tabControllers.get(tabId) || new Set();
  controllers.add(controller);
  tabControllers.set(tabId, controllers);
  return () => {
    controllers.delete(controller);
    if (!controllers.size) tabControllers.delete(tabId);
  };
}

function abortTabControllers(tabId, reason = "Traducao cancelada.") {
  const controllers = tabControllers.get(tabId);
  if (!controllers?.size) return 0;
  let count = 0;
  controllers.forEach((controller) => {
    if (!controller.signal.aborted) {
      controller.abort(reason);
      count += 1;
    }
  });
  tabControllers.delete(tabId);
  return count;
}

async function senderTabExists(sender) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return true;
  try {
    await chrome.tabs.get(tabId);
    return true;
  } catch {
    return false;
  }
}

async function assertSenderTabExists(sender, controller) {
  if (await senderTabExists(sender)) return;
  if (controller) controller.abort();
  throw new Error("Traducao cancelada: a aba foi fechada.");
}

async function translateBubblesStream(payload, form, sender) {
  const controller = new AbortController();
  const forgetController = rememberTabController(sender, controller);
  const timeoutId = setTimeout(() => {
    if (!controller.signal.aborted) controller.abort("Tempo limite da traducao excedido.");
  }, 2 * 60 * 1000);
  try {
    await assertSenderTabExists(sender, controller);
    const response = await fetch(`${SERVER}/api/translate-image-bubbles-stream`, {
      method: "POST",
      body: form,
      signal: controller.signal
    });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `BTA MangaTranslate HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("Streaming response is not available in this browser context.");
  }

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";
  const final = {
    mode: "bubble_overlay",
    imageWidth: 0,
    imageHeight: 0,
    bubbles: [],
    jobId: ""
  };
  let bubblesSinceProgress = 0;

  function sendBubbleSyncProgress() {
    sendProgress(sender, {
      type: "bta-bubble-stream",
      src: payload.src,
      event: {
        type: "sync",
        session_id: payload.sessionId,
        image_width: final.imageWidth,
        image_height: final.imageHeight,
        bubbles: final.bubbles.filter(Boolean)
      }
    });
    bubblesSinceProgress = 0;
  }

  async function applyStreamEvent(event) {
    await assertSenderTabExists(sender, controller);
    if (event.type === "detected") {
      final.imageWidth = event.image_width;
      final.imageHeight = event.image_height;
      final.bubbles = event.bubbles || [];
      final.jobId = event.job_id || "";
    } else if (event.type === "bubble" && event.bubble) {
      const idx = Number(event.bubble.idx) - 1;
      if (idx >= 0) final.bubbles[idx] = { ...(final.bubbles[idx] || {}), ...event.bubble };
      bubblesSinceProgress += 1;
      if (bubblesSinceProgress >= BUBBLE_PROGRESS_FLUSH_SIZE) {
        sendBubbleSyncProgress();
      }
    } else if (event.type === "discard") {
      const idx = Number(event.idx) - 1;
      if (idx >= 0) delete final.bubbles[idx];
    } else if (event.type === "error") {
      throw new Error(event.error || "BTA MangaTranslate stream failed");
    }

  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      await applyStreamEvent(JSON.parse(line));
    }
  }

  const tail = buffer.trim();
  if (tail) await applyStreamEvent(JSON.parse(tail));

  await assertSenderTabExists(sender, controller);
  sendBubbleSyncProgress();

  return final;
  } finally {
    clearTimeout(timeoutId);
    forgetController();
  }
}

async function translateImage(payload, sender) {
  if (isBackendUrl(sender?.tab?.url)) {
    throw new Error("Abra a pagina do manga/manhwa e use a extensao nessa aba. O backend nao deve ser traduzido.");
  }

  await assertSenderTabExists(sender);
  const imageResponse = await fetch(payload.src, {
    credentials: "include",
    cache: "force-cache"
  });
  if (!imageResponse.ok) {
    throw new Error(`Cannot fetch image: HTTP ${imageResponse.status}`);
  }

  const imageBlob = await imageResponse.blob();
  const form = new FormData();
  form.append("file", imageBlob, filenameFromUrl(payload.src));
  form.append("source_lang", payload.sourceLang || "Auto");
  form.append("target_lang", payload.targetLang || "Portuguese (Brazil)");
  form.append("slang_adaptation", String(payload.slangAdaptation ?? true));
  form.append("fast_mode", String(payload.fastMode ?? true));
  form.append("font_path", payload.fontPath || fontPathFromFamily(payload.fontFamily));
  if (payload.fontSize) form.append("font_size", String(payload.fontSize));

  if (payload.renderMode === "bubbles") {
    return translateBubblesStream(payload, form, sender);
  }

  await assertSenderTabExists(sender);
  if (payload.renderMode !== "image" && payload.fastMode !== false) {
    const fastResponse = await fetch(`${SERVER}/api/translate-image-fast`, {
      method: "POST",
      body: form
    });
    if (!fastResponse.ok) {
      const text = await fastResponse.text();
      throw new Error(text || `BTA MangaTranslate HTTP ${fastResponse.status}`);
    }
    const result = await fastResponse.json();
    return {
      mode: "text_overlay",
      sourceText: result.source_text,
      translation: result.translation,
      jobId: result.job_id
    };
  }

  await assertSenderTabExists(sender);
  const translatedResponse = await fetch(`${SERVER}/api/translate-image`, {
    method: "POST",
    body: form
  });
  if (!translatedResponse.ok) {
    const text = await translatedResponse.text();
    throw new Error(text || `BTA MangaTranslate HTTP ${translatedResponse.status}`);
  }

  const result = await translatedResponse.json();
  const outputResponse = await fetch(result.absolute_url || `${SERVER}${result.url}`);
  if (!outputResponse.ok) {
    throw new Error(`Cannot fetch translated image: HTTP ${outputResponse.status}`);
  }

  return {
    mode: "image_overlay",
    dataUrl: await blobToDataUrl(await outputResponse.blob()),
    jobId: result.job_id
  };
}

chrome.tabs.onRemoved.addListener((tabId) => {
  abortTabControllers(tabId, "Traducao cancelada: a aba foi fechada.");
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) {
    abortTabControllers(tabId, "Traducao cancelada: a URL mudou.");
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "bta-translate-visible-screenshot") {
    sendResponse({ ok: false, error: "A captura de viewport foi desativada. Use a traducao direta nas imagens da pagina." });
    return false;
  }

  if (message?.type === "bta-cancel-tab-translations") {
    const tabId = sender?.tab?.id;
    const cancelled = tabId == null ? 0 : abortTabControllers(tabId, "Traducao cancelada pelo usuario.");
    sendResponse({ ok: true, cancelled });
    return false;
  }

  if (message?.type !== "bta-translate-image") return false;

  translateImage(message, sender)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => {
      const errorMessage = error?.name === "AbortError"
        ? "Traducao cancelada pelo usuario."
        : (error?.message || "Traducao cancelada.");
      sendResponse({ ok: false, error: errorMessage });
    });

  return true;
});
