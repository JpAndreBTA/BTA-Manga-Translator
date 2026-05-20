const BTA_BACKEND_HOSTNAMES = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
const BTA_BACKEND_PORTS = new Set(["", "8000", "8001", "8002", "8003", "8004", "8005", "8006", "8007", "8008", "8009", "8010", "8011", "8012", "8013", "8014", "8015", "8016", "8017", "8018", "8019", "8020"]);
const BTA_DISABLE_ON_BACKEND = BTA_BACKEND_HOSTNAMES.has(location.hostname) && BTA_BACKEND_PORTS.has(location.port);

if (BTA_DISABLE_ON_BACKEND) {
  document.querySelectorAll(".bta-viewport-overlay, .bta-bubble-layer, .bta-translation-overlay").forEach((el) => el.remove());
} else {
const MIN_IMAGE_SIZE = 80;
let settings = {
  sourceLang: "Auto",
  targetLang: "Portuguese (Brazil)",
  autoTranslate: false,
  fastMode: true,
  fontSize: 100,
  outlineSize: 4,
  balloonOpacity: 100,
  fontFamily: "Anime Ace",
  slangAdaptation: true
};

let translated = new WeakSet();
let queued = new WeakSet();
let translatedSrcByElement = new WeakMap();
let queuedSrcByElement = new WeakMap();
let buttonTargets = new WeakSet();
let targetStates = new WeakMap();
let failedAt = new WeakMap();
let overlays = new WeakMap();
const bubbleOverlayEntries = new Set();
const activeTranslations = new Map();
const pendingTranslationGroups = new Map();
const translatedResponses = new Map();
const TRANSLATION_CONCURRENCY = 5;
const TRANSLATION_TIMEOUT_MS = 2 * 60 * 1000;
const AUTO_FAILURE_RETRY_MS = 12000;
const AUTO_HEARTBEAT_MS = 800;
const AUTO_BATCH_LIMIT = 5;
const AUTO_BACKGROUND_BATCH_LIMIT = 1;
const AUTO_IDLE_BACKGROUND_BATCH_LIMIT = 3;
const AUTO_RETRY_COOLDOWN_MS = 3500;
const CANDIDATE_SELECTOR = "img, img[data-src], img[data-original], img[data-lazy-src], img[data-original-src], img[data-srcset], img[data-lazy], img[data-image], img[data-full], img[data-url], img[data-cfsrc], canvas, [style*='background-image']";
let queueRunning = false;
let autoTimer = null;
let domRefreshTimer = null;
let bubbleReflowFrame = 0;
const pendingBubbleReflows = new Set();
let pendingAutoRun = false;
let autoTranslateSession = false;
let tabTranslationCancelled = false;
let autoViewportObserver = null;
let autoObservedTargets = new WeakSet();
const autoAttemptedAtBySrc = new Map();
let currentPageUrl = location.href;
let translationSessionId = 1;
const AUTO_PREFETCH_BEHIND_PX = 1400;
const AUTO_PREFETCH_AHEAD_PX = 5200;

document.querySelectorAll(".bta-viewport-overlay").forEach((el) => el.remove());
document.querySelectorAll(".bta-bubble-layer").forEach((el) => el.remove());

chrome.storage.sync.get(settings).then((stored) => {
  if (Number.isFinite(Number(stored.fontSize)) && Number(stored.fontSize) <= 48) {
    stored.fontSize = Math.round((Number(stored.fontSize) / 22) * 100);
  }
  if (stored.balloonOpacity === 90) stored.balloonOpacity = 100;
  if (!Number.isFinite(Number(stored.outlineSize))) stored.outlineSize = settings.outlineSize;
  settings = { ...settings, ...stored };
  autoTranslateSession = Boolean(settings.autoTranslate);
  installButtons();
  if (isAutoTranslateActive()) scheduleAutoTranslate(0);
});

function isAutoTranslateActive() {
  return settings.autoTranslate && autoTranslateSession;
}

function isTabCancelError(error = "") {
  return /aba nao esta mais ativa|aba foi fechada|cancelada pelo usuario|tab is no longer active|no longer active|closed|cancel/i.test(String(error));
}

function cancelBackendTranslations() {
  try {
    const pending = chrome.runtime.sendMessage({ type: "bta-cancel-tab-translations" });
    if (pending && typeof pending.catch === "function") pending.catch(() => {});
  } catch {
    // The background worker may already be gone during tab teardown.
  }
}

function cancelLocalTranslationSession({ cancelBackend = true, preserveAuto = false } = {}) {
  tabTranslationCancelled = true;
  if (!preserveAuto) autoTranslateSession = false;
  pendingAutoRun = false;
  autoAttemptedAtBySrc.clear();
  window.clearTimeout(autoTimer);
  if (cancelBackend) cancelBackendTranslations();
}

function isCandidate(img) {
  return Boolean(candidateFromElement(img, { visibleOnly: true }));
}

function visibleArea(rect) {
  const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
  const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
  return width * height;
}

function bestSrcFromSrcset(value = "") {
  const parts = String(value || "")
    .split(",")
    .map((item) => item.trim().split(/\s+/)[0])
    .filter(Boolean);
  return parts[parts.length - 1] || "";
}

function sourceFromElement(el, { allowLazy = false } = {}) {
  if (el instanceof HTMLCanvasElement) {
    try {
      return el.toDataURL("image/png");
    } catch {
      return "";
    }
  }

  if (el instanceof HTMLImageElement) {
    if (!allowLazy && (!el.complete || !el.naturalWidth || !el.naturalHeight)) return "";
    const lazySrc = allowLazy
      ? (el.dataset.src || el.dataset.original || el.dataset.originalSrc || el.dataset.lazySrc || el.dataset.lazy || el.dataset.image || el.dataset.full || el.dataset.url || el.dataset.cfsrc || el.getAttribute("data-lazy-src") || el.getAttribute("data-src") || el.getAttribute("data-original") || el.getAttribute("data-original-src") || el.getAttribute("data-full") || el.getAttribute("data-url") || el.getAttribute("data-image") || el.getAttribute("data-cfsrc") || bestSrcFromSrcset(el.getAttribute("data-srcset") || el.dataset.srcset || "") || "")
      : "";
    const renderedSrc = el.currentSrc || el.src || "";
    const looksLikePlaceholder = !el.complete || !el.naturalWidth || /^data:image\/(?:gif|svg|png)/i.test(renderedSrc);
    const src = allowLazy && lazySrc && looksLikePlaceholder ? lazySrc : (renderedSrc || lazySrc);
    return src ? new URL(src, location.href).toString() : "";
  }

  const bg = getComputedStyle(el).backgroundImage;
  const match = bg && bg.match(/url\(["']?(.+?)["']?\)/);
  return match ? new URL(match[1], location.href).toString() : "";
}

function candidateFromElement(el, { visibleOnly = false, ignoreFailure = false } = {}) {
  if (!el) return null;
  const lastFailure = failedAt.get(el);
  if (!ignoreFailure && lastFailure && Date.now() - lastFailure < AUTO_FAILURE_RETRY_MS) return null;
  if (el.closest?.(".bta-translation-overlay")) return null;
  if (el.closest?.(".bta-viewport-overlay")) return null;
  const rect = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return null;
  if (rect.width < MIN_IMAGE_SIZE || rect.height < MIN_IMAGE_SIZE) return null;

  const src = sourceFromElement(el, { allowLazy: !visibleOnly });
  if (!src) return null;
  if (translated.has(el)) {
    if (translatedSrcByElement.get(el) === src) return null;
    translated.delete(el);
    translatedSrcByElement.delete(el);
  }
  if (queued.has(el)) {
    if (queuedSrcByElement.get(el) === src) return null;
    queued.delete(el);
    queuedSrcByElement.delete(el);
  }
  if (/\.(svg|ico)(\?|#|$)/i.test(src)) return null;
  if (/avatar|logo|icon|sprite|banner|ads?|tracker|pixel/i.test(src)) return null;

  if (el instanceof HTMLImageElement) {
    const naturalW = el.naturalWidth || rect.width;
    const naturalH = el.naturalHeight || rect.height;
    if (naturalW < 220 || naturalH < 220) return null;
  }

  if (!(el instanceof HTMLImageElement) && !(el instanceof HTMLCanvasElement) && el.querySelector?.("img,canvas")) {
    return null;
  }

  const pageArea = rect.width * rect.height;
  const area = visibleOnly ? visibleArea(rect) : pageArea;
  if (area < 40000) return null;
  if (visibleOnly && (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth)) {
    return null;
  }

  return { el, src, rect, area, pageArea, top: rect.top + window.scrollY, left: rect.left + window.scrollX };
}

function setState(img, state) {
  targetStates.set(img, state);
}

function markQueued(candidate) {
  queued.add(candidate.el);
  queuedSrcByElement.set(candidate.el, candidate.src);
}

function unmarkQueued(el) {
  queued.delete(el);
  queuedSrcByElement.delete(el);
}

function markTranslated(candidate) {
  translated.add(candidate.el);
  translatedSrcByElement.set(candidate.el, candidate.src);
}

function fontStack(name) {
  if (name === "Anime Ace") return "'Anime Ace 2.0 BB', 'Anime Ace', 'AnimeAce', 'Anime Ace 2.0', 'CC Wild Words', 'Comic Sans MS', Arial, sans-serif";
  if (name === "Impact") return "Impact, Haettenschweiler, 'Arial Narrow Bold', sans-serif";
  if (name === "Comic Bold") return "'Comic Sans MS', 'Arial Rounded MT Bold', Arial, sans-serif";
  if (name === "Marker") return "'Permanent Marker', 'Segoe Print', 'Comic Sans MS', cursive";
  return "Inter, 'Trebuchet MS', 'Arial Black', Arial, sans-serif";
}

function applyRenderSettings(root = document) {
  const fontScale = clamp(Number(settings.fontSize) || 100, 50, 220) / 100;
  const fontSize = Math.round(14 * fontScale);
  const opacity = Math.max(20, Math.min(100, Number(settings.balloonOpacity) || 100)) / 100;
  const family = fontStack(settings.fontFamily);

  const overlays = root.classList?.contains("bta-translation-overlay")
    ? [root]
    : [...root.querySelectorAll(".bta-translation-overlay")];

  overlays.forEach((overlay) => {
    overlay.style.backgroundColor = `rgba(8, 8, 11, ${opacity})`;
    const body = overlay.querySelector(".bta-translation-body");
    if (body) {
      body.style.fontFamily = family;
      body.style.fontSize = `${fontSize}px`;
    }
  });

  document.querySelectorAll(".bta-bubble-text").forEach((node) => {
    const copy = getBubbleCopy(node);
    copy.style.fontFamily = family;
    applyBubbleVisuals(node, {
      background_color: node.dataset.btaBubbleBackground,
      text_color: node.dataset.btaBubbleColor,
      shape: node.dataset.btaBubbleShape,
      translation: copy.textContent
    });
  });
  scheduleBubbleOverlayReflow();
}

function showTextOverlay(target, response) {
  const old = overlays.get(target);
  if (old) old.remove();

  const overlay = document.createElement("section");
  overlay.className = "bta-translation-overlay";
  overlay.innerHTML = `
    <div class="bta-translation-head">
      <strong>BTA MangaTranslate - texto visivel</strong>
      <button type="button" title="Fechar">x</button>
    </div>
    <div class="bta-translation-body"></div>
    <details class="bta-translation-source">
      <summary>OCR original</summary>
      <pre></pre>
    </details>
  `;

  const body = overlay.querySelector(".bta-translation-body");
  const source = overlay.querySelector("pre");
  body.textContent = response.translation || "No translation returned.";
  source.textContent = response.sourceText || "";
  overlay.querySelector("button").addEventListener("click", () => overlay.remove());
  applyRenderSettings(overlay);

  const parent = target.parentElement;
  if (parent) {
    parent.insertBefore(overlay, target);
  } else {
    document.body.prepend(overlay);
  }
  overlays.set(target, overlay);
}

function removeBubbleOverlay(target) {
  for (const entry of [...bubbleOverlayEntries]) {
    if (entry.target === target) {
      entry.layer.remove();
      bubbleOverlayEntries.delete(entry);
    }
  }
}

function findBubbleEntry(target) {
  for (const entry of bubbleOverlayEntries) {
    if (entry.target === target) return entry;
  }
  return null;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function rememberTranslatedResponse(src, response) {
  if (!src || !response?.bubbles?.length) return;
  if (responseHasPendingBubbles(response)) return;
  translatedResponses.set(src, response);
  if (translatedResponses.size > 80) {
    translatedResponses.delete(translatedResponses.keys().next().value);
  }
}

function responseHasPendingBubbles(response) {
  return (response?.bubbles || []).some((bubble) => (
    bubble
    && String(bubble.text || "").trim()
    && !visibleBubbleTranslation(bubble.translation || "")
  ));
}

function bubbleBackgroundColor(baseColor) {
  const opacity = Math.max(20, Math.min(100, Number(settings.balloonOpacity) || 100)) / 100;
  const match = String(baseColor || "").match(/\d+(\.\d+)?/g);
  if (!match || match.length < 3) return `rgba(255, 255, 255, ${opacity})`;
  let [r, g, b] = match.map((value) => Number(value));
  const spread = Math.max(r, g, b) - Math.min(r, g, b);
  if (spread < 28 && ((0.2126 * r) + (0.7152 * g) + (0.0722 * b)) > 135) {
    r = 255; g = 255; b = 255;
  }
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function rgbValues(color, fallback = [255, 255, 255]) {
  const match = String(color || "").match(/\d+(\.\d+)?/g);
  if (!match || match.length < 3) return fallback;
  return match.slice(0, 3).map((value) => Number(value));
}

function solidBubbleColor(baseColor) {
  const [r, g, b] = rgbValues(baseColor, [255, 255, 255]);
  return `rgb(${r}, ${g}, ${b})`;
}

function outlineSize() {
  return Math.max(0, Number(settings.outlineSize) || 4);
}

function luminanceFromColor(color) {
  const [r, g, b] = rgbValues(color, [255, 255, 255]);
  return (0.2126 * r) + (0.7152 * g) + (0.0722 * b);
}

function fallbackTextColor(background) {
  return luminanceFromColor(background) >= 145 ? "#111111" : "#f8f8f8";
}

function bubbleOriginalIndex(bubble, fallbackIndex = 0) {
  const idx = Number(bubble?.idx);
  return Number.isFinite(idx) && idx > 0 ? idx - 1 : fallbackIndex;
}

function foldBubbleText(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function collapseRepeatedBubbleText(text) {
  const lines = String(text || "")
    .replace(/\r/g, "")
    .split("\n");
  const seen = [];
  const out = [];
  for (const rawLine of lines) {
    let line = rawLine.trim();
    line = line.replace(/\b([\p{L}\p{N}']{3,})(?:[\s,;:/-]+\1\b){2,}/giu, "$1");
    line = line.replace(/\b([\p{L}\p{N}']{5,})\s+\1\b/giu, "$1");
    const normalized = foldBubbleText(line).replace(/[^a-z0-9]+/g, " ").trim();
    if (!normalized) {
      if (out.length && out[out.length - 1]) out.push("");
      continue;
    }
    if (seen.includes(normalized)) continue;
    if (normalized.length <= 14 && seen.some((other) => other !== normalized && other.includes(normalized) && other.length >= normalized.length * 2)) {
      continue;
    }
    out.push(line);
    seen.push(normalized);
    while (seen.length > 6) seen.shift();
  }
  while (out.length && !out[out.length - 1]) out.pop();
  return out.join("\n").trim();
}

function joinDialogueLines(lines) {
  let current = "";
  for (const rawLine of lines) {
    const line = String(rawLine || "").replace(/\s+/g, " ").trim();
    if (!line) continue;
    if (!current) {
      current = line;
    } else if (current.endsWith("-")) {
      const prefix = current.slice(0, -1).trim();
      if (prefix.length >= 1 && prefix.length <= 3 && line.toLowerCase().startsWith(prefix.toLowerCase())) {
        current = `${current.trimEnd()}${line.trimStart()}`;
      } else {
        current = `${current.slice(0, -1).trimEnd()}${line.trimStart()}`;
      }
    } else if (/^[,.;:!?%)}\]\u2026]/u.test(line)) {
      current = `${current.trimEnd()}${line}`;
    } else if (/[(\[{¿¡]$/u.test(current)) {
      current = `${current.trimEnd()}${line.trimStart()}`;
    } else {
      current = `${current.trimEnd()} ${line.trimStart()}`;
    }
  }
  return current
    .replace(/\s+([,.;:!?%)}\]\u2026])/gu, "$1")
    .replace(/([({\[¿¡])\s+/gu, "$1")
    .replace(/\.{3,}/g, "...")
    .replace(/\s+/g, " ")
    .trim();
}

function mergeSoftBubbleLineBreaks(text) {
  return String(text || "")
    .replace(/\r/g, "\n")
    .split(/\n\s*\n+/)
    .map((paragraph) => joinDialogueLines(paragraph.split(/\n+/)))
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

function visibleBubbleTranslation(text) {
  const value = mergeSoftBubbleLineBreaks(collapseRepeatedBubbleText(String(text || "").trim()));
  const lowered = foldBubbleText(value);
  const blocked = [
    "please provide",
    "provide the ocr",
    "ocr text",
    "actual text",
    "i need the",
    "cannot translate",
    "can't translate",
    "unable to translate",
    "as an ai",
    "no translation",
    "manga bubble",
    "bubble image",
    "visible line",
    "visible text",
    "return only",
    "transcribe only",
    "read only",
    "leia apenas",
    "apenas o texto",
    "texto impresso",
    "texto visivel",
    "retorne apenas",
    "sem explicacao",
    "nao ha texto",
    "nao consigo"
  ];
  const words = lowered.match(/[a-z0-9']+/g) || [];
  if (words.length >= 6) {
    const counts = new Map();
    words.forEach((word) => counts.set(word, (counts.get(word) || 0) + 1));
    for (const [word, count] of counts.entries()) {
      if (word.length >= 3 && count >= 4 && count / words.length >= 0.38) return "";
    }
  }
  return blocked.some((fragment) => lowered.includes(fragment)) ? "" : value;
}

function getBubbleCopy(node) {
  return node.querySelector(".bta-bubble-copy") || node;
}

function getBubbleFill(node) {
  let fill = node.querySelector(".bta-bubble-fill");
  if (fill) return fill;
  fill = document.createElement("div");
  fill.className = "bta-bubble-fill";
  node.insertBefore(fill, node.firstChild);
  return fill;
}

function originalLineProfile(originalText = "", fallbackLineCount = 1) {
  const rawLines = String(originalText || "")
    .replace(/\r/g, "")
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  if (!rawLines.length) {
    const count = clamp(Number(fallbackLineCount) || 1, 1, 8);
    return { lineCount: count, maxLineChars: 0, avgLineChars: 0 };
  }
  const lengths = rawLines.map((line) => line.length);
  const maxLineChars = Math.max(...lengths);
  const avgLineChars = lengths.reduce((sum, length) => sum + length, 0) / lengths.length;
  return {
    lineCount: clamp(rawLines.length, 1, 8),
    maxLineChars,
    avgLineChars
  };
}

function targetLineCountForTranslation(value, lineCount = 1, originalText = "") {
  const words = String(value || "").split(/\s+/).filter(Boolean);
  if (words.length <= 1) return 1;

  const profile = originalLineProfile(originalText, lineCount);
  let desired = Math.max(Number(lineCount) || 1, profile.lineCount);
  if (profile.maxLineChars > 0) {
    const charRatio = value.length / Math.max(1, profile.maxLineChars);
    desired = Math.max(desired, Math.ceil(charRatio * 0.92));
  } else if (value.length >= 34) {
    desired = Math.max(desired, Math.ceil(value.length / 18));
  }
  return clamp(Math.min(desired, words.length), 1, 8);
}

function balanceWordsIntoLines(value, lineCount = 1, originalText = "") {
  value = visibleBubbleTranslation(value).trim();
  if (!value || value.includes("\n")) {
    return value
      .split(/\r?\n/)
      .map((line) => line.trim())
      .join("\n")
      .trim();
  }

  const words = value.split(/\s+/).filter(Boolean);
  let desired = targetLineCountForTranslation(value, lineCount, originalText);
  desired = Math.min(desired, words.length);
  if (desired <= 1 || value.length < 24) return value;
  if (value.length < 42) desired = Math.min(desired, Math.max(2, Number(lineCount) || 1));

  const lines = [];
  const totalChars = words.reduce((sum, word) => sum + word.length, 0) + Math.max(0, words.length - 1);
  const profile = originalLineProfile(originalText, desired);
  const target = Math.max(7, Math.min(
    Math.ceil(totalChars / desired),
    profile.maxLineChars ? Math.ceil(profile.maxLineChars * 1.35) : 18
  ));
  let current = "";

  words.forEach((word, index) => {
    const next = current ? `${current} ${word}` : word;
    const remainingSlots = desired - lines.length - 1;
    const remainingWords = words.length - index - 1;
    if (current && next.length > target && remainingSlots > 0 && remainingWords >= remainingSlots) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  });
  if (current) lines.push(current);
  return lines.join("\n");
}

function shouldUppercaseLikeOriginal(originalText = "") {
  const letters = String(originalText).match(/\p{L}/gu) || [];
  if (letters.length < 3) return true;
  const upper = letters.filter((ch) => ch === ch.toLocaleUpperCase("pt-BR") && ch !== ch.toLocaleLowerCase("pt-BR")).length;
  return upper / letters.length >= 0.65;
}

function applyOriginalCase(text, originalText = "") {
  return shouldUppercaseLikeOriginal(originalText) ? text.toLocaleUpperCase("pt-BR") : text;
}

function balanceBubbleLines(text, lineCount = 1, paragraphCount = 1, originalText = "") {
  const value = visibleBubbleTranslation(text)
    .replace(/\r/g, "")
    .replace(/[ \t]+/g, " ")
    .trim();
  if (!value) return "";
  if (value.includes("\n")) {
    const preserved = value
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)
      .join("\n");
    return applyOriginalCase(preserved, originalText);
  }

  const paragraphs = clamp(Number(paragraphCount) || 1, 1, 4);
  if (paragraphs <= 1 || value.length < 54) {
    return applyOriginalCase(balanceWordsIntoLines(value, lineCount, originalText), originalText);
  }

  const sentences = value.match(/[^.!?;:]+[.!?;:]?/g)?.map((part) => part.trim()).filter(Boolean) || [value];
  if (sentences.length <= 1) return applyOriginalCase(balanceWordsIntoLines(value, lineCount, originalText), originalText);

  const buckets = Array.from({ length: Math.min(paragraphs, sentences.length) }, () => "");
  sentences.forEach((sentence) => {
    let target = 0;
    for (let i = 1; i < buckets.length; i += 1) {
      if (buckets[i].length < buckets[target].length) target = i;
    }
    buckets[target] = buckets[target] ? `${buckets[target]} ${sentence}` : sentence;
  });

  const linesPerParagraph = Math.max(1, Math.ceil((Number(lineCount) || buckets.length) / buckets.length));
  const balanced = buckets
    .map((paragraph) => balanceWordsIntoLines(paragraph, linesPerParagraph, originalText))
    .filter(Boolean)
    .join("\n");
  return applyOriginalCase(balanced, originalText);
}

function setBubbleCopyText(node, bubble = {}) {
  getBubbleCopy(node).textContent = balanceBubbleLines(
    bubble.translation || "",
    bubble.line_count,
    bubble.paragraph_count,
    bubble.text || ""
  );
}

function applyBubbleVisuals(node, bubble = {}) {
  const background = bubble.background_color || node.dataset.btaBubbleBackground || "rgb(255, 255, 255)";
  const textColor = bubble.text_color || node.dataset.btaBubbleColor || fallbackTextColor(background);
  node.dataset.btaBubbleBackground = background;
  node.dataset.btaBubbleColor = textColor;
  node.dataset.btaBubbleShape = bubble.shape || node.dataset.btaBubbleShape || "round";
  node.style.background = "transparent";
  node.style.boxShadow = "none";
  node.style.color = textColor;
  node.style.textShadow = "none";
  node.style.fontFamily = fontStack(settings.fontFamily);
  const fill = getBubbleFill(node);
  fill.style.background = bubbleBackgroundColor(background);
  const copy = getBubbleCopy(node);
  copy.style.fontFamily = fontStack(settings.fontFamily);
  copy.style.color = textColor;
  copy.style.textShadow = "none";
  copy.style.webkitTextStroke = "0 transparent";
  copy.style.paintOrder = "normal";
  node.classList.toggle("bta-bubble-pending", !visibleBubbleTranslation(bubble.translation || getBubbleCopy(node).textContent));
}

function createBubbleNode(bubble, fallbackIndex = 0) {
  const node = document.createElement("div");
  node.className = "bta-bubble-text";
  node.dataset.btaBubbleIndex = String(bubbleOriginalIndex(bubble, fallbackIndex));
  const fill = document.createElement("div");
  fill.className = "bta-bubble-fill";
  const copy = document.createElement("div");
  copy.className = "bta-bubble-copy";
  node.append(fill);
  node.append(copy);
  setBubbleCopyText(node, bubble);
  node.title = bubble.text || "";
  applyBubbleVisuals(node, { ...bubble, translation: getBubbleCopy(node).textContent });
  return node;
}

function bubbleBorderRadius(shape, width, height, klass = "") {
  const aspect = width / Math.max(1, height);
  if (shape === "rect" || shape === "square") return "8px";
  if (shape === "wide" || aspect > 2.75) return "50% / 38%";
  if (shape === "tall" || aspect < 0.72) return "42% / 50%";
  if (shape === "oval" || shape === "round" || shape === "soft") return "50% / 44%";
  return "46% / 42%";
}

function originalTextLineMetrics(bubble, displayW, displayH) {
  const profile = originalLineProfile(bubble?.text || "", bubble?.line_count || 1);
  const lineCount = Math.max(1, profile.lineCount || Number(bubble?.line_count) || 1);
  const baseFromHeight = displayH / Math.max(1.0, lineCount * 1.02);
  const baseFromWidth = profile.maxLineChars
    ? displayW / Math.max(4, profile.maxLineChars * 0.48)
    : baseFromHeight;
  const sourceSize = profile.maxLineChars
    ? Math.min(baseFromHeight, Math.max(baseFromWidth, baseFromHeight * 0.72))
    : baseFromHeight;
  return {
    lineCount,
    originalFontSize: clamp(Math.round(sourceSize * 1.12), 10, 72),
    maxLineChars: profile.maxLineChars,
    avgLineChars: profile.avgLineChars
  };
}

function estimateBubbleFontSize(bubble, displayW, displayH) {
  const detected = Number(bubble.detected_font_size || 0);
  const metrics = originalTextLineMetrics(bubble, displayW, displayH);
  const lineCap = Math.max(6, Math.floor(displayH / Math.max(1, metrics.lineCount) * 0.72));
  const boxCap = Math.max(8, Math.floor(displayH * 0.48));
  const detectedCap = detected > 0 ? Math.max(7, Math.round(detected * 1.08)) : 72;
  const base = detected > 0 ? detected : metrics.originalFontSize;
  return clamp(Math.round(base), 6, Math.min(54, boxCap, lineCap, detectedCap));
}

function currentFontScale() {
  return clamp(Number(settings.fontSize) || 100, 50, 220) / 100;
}

function applyFontScaleToFitSize(autoSize) {
  return clamp(Math.round(autoSize * currentFontScale()), 5, 132);
}

function fitBubbleText(copy, maxSize) {
  let low = 5;
  let high = Math.max(low, Math.round(maxSize * currentFontScale()));
  let best = low;
  let checks = 0;
  while (low <= high && checks < 10) {
    const mid = Math.floor((low + high) / 2);
    copy.style.fontSize = `${mid}px`;
    const fitsHeight = copy.scrollHeight <= copy.clientHeight + 1;
    const fitsWidth = copy.scrollWidth <= copy.clientWidth + 1;
    if (fitsHeight && fitsWidth) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
    checks += 1;
  }
  copy.style.fontSize = `${best}px`;
  copy.style.transform = "none";
  if (copy.scrollHeight > copy.clientHeight + 1 || copy.scrollWidth > copy.clientWidth + 1) {
    const scaleX = copy.clientWidth / Math.max(1, copy.scrollWidth);
    const scaleY = copy.clientHeight / Math.max(1, copy.scrollHeight);
    const scale = clamp(Math.min(scaleX, scaleY), 0.32, 1);
    copy.style.transform = `scale(${scale})`;
  }
}

function bubbleLineHeight(lines) {
  if (lines <= 2) return 1.05;
  if (lines <= 4) return 1.08;
  return 1.12;
}

function bubbleTextAlign(bubble = {}) {
  const klass = String(bubble.class || "");
  const shape = String(bubble.shape || "");
  const requested = String(bubble.text_align || "").toLowerCase();
  if (klass === "text_free") {
    return ["left", "center", "right"].includes(requested) ? requested : "center";
  }
  return "center";
}

function clampImageBox(x, y, w, h, imageW, imageH) {
  const safeX = clamp(x, 0, Math.max(0, imageW - 1));
  const safeY = clamp(y, 0, Math.max(0, imageH - 1));
  const safeW = clamp(w, 1, Math.max(1, imageW - safeX));
  const safeH = clamp(h, 1, Math.max(1, imageH - safeY));
  return { x: safeX, y: safeY, w: safeW, h: safeH };
}

function compactOverlayBoxForBubble(bubble, balloonBox, textBox, maxW, maxH) {
  const klass = String(bubble.class || "");
  if (klass === "text_free") return textBox;
  const padX = clamp(Math.round(textBox.w * 0.10), 4, 18);
  const padY = clamp(Math.round(textBox.h * 0.12), 3, 16);
  const maxAllowedW = Math.min(maxW, Math.max(textBox.w + padX * 2, Math.min(balloonBox.w * 0.62, textBox.w * 1.28)));
  const maxAllowedH = Math.min(maxH, Math.max(textBox.h + padY * 2, Math.min(balloonBox.h * 0.58, textBox.h * 1.32)));
  const w = clamp(textBox.w + padX * 2, Math.min(maxW, textBox.w), maxAllowedW);
  const h = clamp(textBox.h + padY * 2, Math.min(maxH, textBox.h), maxAllowedH);
  return {
    x: clamp(textBox.x + textBox.w / 2 - w / 2, 0, Math.max(0, maxW - w)),
    y: clamp(textBox.y + textBox.h / 2 - h / 2, 0, Math.max(0, maxH - h)),
    w,
    h
  };
}

function textContentBoxForBubble(bubble, overlayBox) {
  const klass = String(bubble.class || "");
  const shape = String(bubble.shape || "");
  const isRect = shape === "rect" || shape === "square";
  const padX = klass === "text_free" ? 0 : clamp(Math.round(overlayBox.w * (isRect ? 0.05 : 0.08)), 3, 16);
  const padY = klass === "text_free" ? 0 : clamp(Math.round(overlayBox.h * (isRect ? 0.06 : 0.09)), 2, 14);
  return {
    x: overlayBox.x + padX,
    y: overlayBox.y + padY,
    w: Math.max(10, overlayBox.w - padX * 2),
    h: Math.max(10, overlayBox.h - padY * 2)
  };
}

function positionBubbleEntry(entry) {
  if (!document.documentElement.contains(entry.target)) {
    entry.layer.remove();
    bubbleOverlayEntries.delete(entry);
    return;
  }

  const rect = entry.target.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  const imageWidth = entry.response.imageWidth || entry.target.naturalWidth || rect.width;
  const imageHeight = entry.response.imageHeight || entry.target.naturalHeight || rect.height;
  const scaleX = rect.width / imageWidth;
  const scaleY = rect.height / imageHeight;
  const leftBase = rect.left + window.scrollX;
  const topBase = rect.top + window.scrollY;

  entry.layer.querySelectorAll(".bta-bubble-text").forEach((node) => {
    const bubble = entry.response.bubbles[Number(node.dataset.btaBubbleIndex)];
    if (!bubble) return;

    const rawX = Number(bubble.x) || 0;
    const rawY = Number(bubble.y) || 0;
    const rawW = Number(bubble.w) || 1;
    const rawH = Number(bubble.h) || 1;
    const textRawX = Number(bubble.text_x ?? rawX) || rawX;
    const textRawY = Number(bubble.text_y ?? rawY) || rawY;
    const textRawW = Number(bubble.text_w ?? rawW) || rawW;
    const textRawH = Number(bubble.text_h ?? rawH) || rawH;
    const imageBox = clampImageBox(rawX, rawY, rawW, rawH, imageWidth, imageHeight);
    const imageTextBox = clampImageBox(textRawX, textRawY, textRawW, textRawH, imageWidth, imageHeight);
    const balloonBox = {
      x: imageBox.x * scaleX,
      y: imageBox.y * scaleY,
      w: imageBox.w * scaleX,
      h: imageBox.h * scaleY
    };
    const textBox = {
      x: imageTextBox.x * scaleX,
      y: imageTextBox.y * scaleY,
      w: imageTextBox.w * scaleX,
      h: imageTextBox.h * scaleY
    };
    const overlayBox = compactOverlayBoxForBubble(bubble, balloonBox, textBox, rect.width, rect.height);
    const contentBox = textContentBoxForBubble(bubble, overlayBox);
    const text = balanceBubbleLines(
      bubble.translation || "",
      bubble.line_count,
      bubble.paragraph_count,
      bubble.text || ""
    ).trim();
    const lines = Math.max(1, text.split(/\r?\n/).filter(Boolean).length);
    const extraPad = outlineSize();
    const lineHeight = bubbleLineHeight(lines);
    const maxFontSize = estimateBubbleFontSize(bubble, textBox.w, textBox.h);
    const finalW = clamp(overlayBox.w, 12, rect.width);
    const finalH = clamp(overlayBox.h, 10, rect.height);
    const finalLeft = clamp(overlayBox.x, 0, Math.max(0, rect.width - finalW));
    const finalTop = clamp(overlayBox.y, 0, Math.max(0, rect.height - finalH));

    node.style.left = `${leftBase + finalLeft}px`;
    node.style.top = `${topBase + finalTop}px`;
    node.style.width = `${finalW}px`;
    node.style.height = `${finalH}px`;
    const radius = bubbleBorderRadius(bubble.shape || node.dataset.btaBubbleShape, finalW, finalH, bubble.class || "");
    node.style.borderRadius = radius;
    node.style.padding = "0";
    const fill = getBubbleFill(node);
    fill.style.borderRadius = radius;
    const copy = getBubbleCopy(node);
    const localContentX = clamp(contentBox.x - finalLeft, 0, Math.max(0, finalW - 1));
    const localContentY = clamp(contentBox.y - finalTop, 0, Math.max(0, finalH - 1));
    const padX = Math.max(3, extraPad);
    const padY = Math.max(2, extraPad);
    const copyLeft = clamp(localContentX + padX, 0, Math.max(0, finalW - 1));
    const copyTop = clamp(localContentY + padY, 0, Math.max(0, finalH - 1));
    const copyW = Math.max(10, Math.min(contentBox.w - padX * 2, finalW - copyLeft));
    const copyH = Math.max(10, Math.min(contentBox.h - padY * 2, finalH - copyTop));
    const align = bubbleTextAlign(bubble);
    const valign = bubble.class === "text_free" && ["top", "middle", "bottom"].includes(bubble.text_valign)
      ? bubble.text_valign
      : "middle";

    copy.style.left = `${copyLeft}px`;
    copy.style.top = `${copyTop}px`;
    copy.style.width = `${copyW}px`;
    copy.style.height = `${copyH}px`;
    copy.style.textAlign = align;
    copy.style.justifyContent = align === "left" ? "flex-start" : align === "right" ? "flex-end" : "center";
    copy.style.alignItems = valign === "top" ? "flex-start" : valign === "bottom" ? "flex-end" : "center";
    copy.style.letterSpacing = "0";
    copy.style.lineHeight = String(lineHeight);
    setBubbleCopyText(node, bubble);
    fitBubbleText(copy, maxFontSize);
    copy.style.webkitTextStroke = "0 transparent";
    copy.style.textShadow = "none";
  });
}

function reflowBubbleOverlays() {
  bubbleReflowFrame = 0;
  pendingBubbleReflows.clear();
  bubbleOverlayEntries.forEach(positionBubbleEntry);
}

function scheduleBubbleEntryReflow(entry) {
  pendingBubbleReflows.add(entry);
  if (bubbleReflowFrame) return;
  bubbleReflowFrame = requestAnimationFrame(() => {
    const entries = [...pendingBubbleReflows];
    pendingBubbleReflows.clear();
    bubbleReflowFrame = 0;
    entries.forEach(positionBubbleEntry);
  });
}

function scheduleBubbleOverlayReflow() {
  bubbleOverlayEntries.forEach((entry) => pendingBubbleReflows.add(entry));
  if (bubbleReflowFrame) return;
  bubbleReflowFrame = requestAnimationFrame(() => {
    const entries = [...pendingBubbleReflows];
    pendingBubbleReflows.clear();
    bubbleReflowFrame = 0;
    entries.forEach(positionBubbleEntry);
  });
}

function applyBubbleTranslations(candidate, response, allowEmpty = false) {
  const bubbles = (response.bubbles || []).filter((bubble) => allowEmpty || visibleBubbleTranslation(bubble.translation));
  if (!bubbles.length) return false;

  let entry = findBubbleEntry(candidate.el);
  if (!entry) {
    const layer = document.createElement("div");
    layer.className = "bta-bubble-layer";
    document.documentElement.append(layer);
    entry = {
      target: candidate.el,
      layer,
      response: {
        mode: "bubble_overlay",
        imageWidth: response.imageWidth || response.image_width || candidate.el.naturalWidth || candidate.rect?.width || 0,
        imageHeight: response.imageHeight || response.image_height || candidate.el.naturalHeight || candidate.rect?.height || 0,
        bubbles: []
      }
    };
    bubbleOverlayEntries.add(entry);
  } else {
    entry.response.imageWidth = response.imageWidth || response.image_width || entry.response.imageWidth;
    entry.response.imageHeight = response.imageHeight || response.image_height || entry.response.imageHeight;
  }

  const sparseBubbles = [];
  const validIndexes = new Set();

  bubbles.forEach((bubble, index) => {
    const originalIndex = bubbleOriginalIndex(bubble, index);
    validIndexes.add(originalIndex);
    sparseBubbles[originalIndex] = bubble;
    entry.response.bubbles[originalIndex] = { ...(entry.response.bubbles[originalIndex] || {}), ...bubble };
    const node = ensureBubbleNode(entry, entry.response.bubbles[originalIndex], originalIndex);
    setBubbleCopyText(node, entry.response.bubbles[originalIndex]);
    node.title = bubble.text || "";
    applyBubbleVisuals(node, { ...entry.response.bubbles[originalIndex], translation: getBubbleCopy(node).textContent });
  });

  entry.layer.querySelectorAll(".bta-bubble-text").forEach((node) => {
    const index = Number(node.dataset.btaBubbleIndex);
    if (!validIndexes.has(index)) node.remove();
  });
  entry.response.bubbles = sparseBubbles;
  positionBubbleEntry(entry);
  requestAnimationFrame(() => positionBubbleEntry(entry));
  return true;
}

function ensureBubbleEntry(candidate, response = {}) {
  let entry = findBubbleEntry(candidate.el);
  if (entry) return entry;

  const layer = document.createElement("div");
  layer.className = "bta-bubble-layer";
  document.documentElement.append(layer);
  entry = {
    target: candidate.el,
    layer,
    response: {
      mode: "bubble_overlay",
      imageWidth: response.imageWidth || response.image_width || candidate.el.naturalWidth || candidate.rect?.width || 0,
      imageHeight: response.imageHeight || response.image_height || candidate.el.naturalHeight || candidate.rect?.height || 0,
      bubbles: []
    }
  };
  bubbleOverlayEntries.add(entry);
  positionBubbleEntry(entry);
  return entry;
}

function ensureBubbleNode(entry, bubble, index) {
  let node = entry.layer.querySelector(`.bta-bubble-text[data-bta-bubble-index="${index}"]`);
  if (node) return node;
  node = createBubbleNode(bubble, index);
  entry.layer.append(node);
  return node;
}

function updateBubbleTranslation(candidate, bubble) {
  const entry = ensureBubbleEntry(candidate, {
    imageWidth: bubble?.image_width,
    imageHeight: bubble?.image_height
  });
  if (!entry || !bubble) return false;

  const index = Math.max(0, Number(bubble.idx || 1) - 1);
  entry.response.bubbles[index] = { ...(entry.response.bubbles[index] || {}), ...bubble };

  const node = ensureBubbleNode(entry, entry.response.bubbles[index], index);
  setBubbleCopyText(node, bubble);
  node.title = bubble.text || "";
  applyBubbleVisuals(node, { ...entry.response.bubbles[index], translation: getBubbleCopy(node).textContent });
  scheduleBubbleEntryReflow(entry);
  return Boolean(node.textContent.trim());
}

function discardBubble(candidate, idx) {
  const entry = findBubbleEntry(candidate.el);
  if (!entry) return;
  const index = Math.max(0, Number(idx || 1) - 1);
  delete entry.response.bubbles[index];
  entry.layer.querySelector(`.bta-bubble-text[data-bta-bubble-index="${index}"]`)?.remove();
}

function resetPageTranslations({ preserveAuto = false } = {}) {
  const shouldResumeAuto = preserveAuto && Boolean(settings.autoTranslate);
  cancelLocalTranslationSession({ preserveAuto });
  bubbleOverlayEntries.forEach((entry) => {
    queued.delete(entry.target);
    translated.delete(entry.target);
    failedAt.delete(entry.target);
    targetStates.delete(entry.target);
    translatedSrcByElement.delete(entry.target);
    queuedSrcByElement.delete(entry.target);
    entry.layer.remove();
  });
  bubbleOverlayEntries.clear();
  document.querySelectorAll(".bta-translation-overlay").forEach((overlay) => overlay.remove());
  document.querySelectorAll(".bta-hover-button").forEach((button) => button.remove());
  pendingTranslationGroups.clear();
  activeTranslations.clear();
  translatedResponses.clear();
  translated = new WeakSet();
  queued = new WeakSet();
  translatedSrcByElement = new WeakMap();
  queuedSrcByElement = new WeakMap();
  targetStates = new WeakMap();
  failedAt = new WeakMap();
  overlays = new WeakMap();
  buttonTargets = new WeakSet();
  if (autoViewportObserver) autoViewportObserver.disconnect();
  autoViewportObserver = null;
  autoObservedTargets = new WeakSet();
  if (shouldResumeAuto) {
    autoTranslateSession = true;
    tabTranslationCancelled = false;
  }
}

function handleBubbleStreamEvent(src, event) {
  if (event?.session_id && Number(event.session_id) !== translationSessionId) return;
  const candidates = activeTranslations.get(src);
  if (!candidates?.size || !event) return;

  if (event.type === "detected") {
    candidates.forEach((candidate) => ensureBubbleEntry(candidate, {
      mode: "bubble_overlay",
      imageWidth: event.image_width,
      imageHeight: event.image_height,
      bubbles: []
    }));
    return;
  }

  if (event.type === "bubble") {
    if (!visibleBubbleTranslation(event.bubble?.translation)) {
      candidates.forEach((candidate) => discardBubble(candidate, event.bubble?.idx || event.idx));
      return;
    }
    candidates.forEach((candidate) => updateBubbleTranslation(candidate, {
      ...event.bubble,
      image_width: event.image_width,
      image_height: event.image_height
    }));
  }

  if (event.type === "sync") {
    const bubbles = (event.bubbles || []).filter((bubble) => visibleBubbleTranslation(bubble.translation));
    candidates.forEach((candidate) => {
      bubbles.forEach((bubble) => updateBubbleTranslation(candidate, {
        ...bubble,
        image_width: event.image_width,
        image_height: event.image_height
      }));
    });
  }

  if (event.type === "discard") {
    candidates.forEach((candidate) => discardBubble(candidate, event.idx));
  }
}

function translateImage(target) {
  const candidate = candidateFromElement(target);
  if (!candidate) return false;
  translateCandidate(candidate);
  return true;
}

function translateCandidate(candidate) {
  if (queued.has(candidate.el) || translated.has(candidate.el)) return Promise.resolve(false);
  const sessionId = translationSessionId;

  const cached = translatedResponses.get(candidate.src);
  if (cached) {
    markQueued(candidate);
    setState(candidate.el, "working");
    const ok = applyBubbleTranslations(candidate, cached);
    unmarkQueued(candidate.el);
    if (ok) {
      markTranslated(candidate);
      failedAt.delete(candidate.el);
      setState(candidate.el, "done");
    } else {
      setState(candidate.el, "error");
    }
    return Promise.resolve(ok);
  }

  const existingGroup = pendingTranslationGroups.get(candidate.src);
  if (existingGroup) {
    markQueued(candidate);
    existingGroup.candidates.add(candidate);
    setState(candidate.el, "working");
    return new Promise((resolve) => {
      existingGroup.resolvers.push({ candidate, resolve });
    });
  }

  markQueued(candidate);
  const group = { candidates: new Set([candidate]), resolvers: [], sessionId };
  pendingTranslationGroups.set(candidate.src, group);
  activeTranslations.set(candidate.src, group.candidates);
  setState(candidate.el, "working");

  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      resolve(value);
    };
    const timeoutId = window.setTimeout(() => {
      pendingTranslationGroups.delete(candidate.src);
      activeTranslations.delete(candidate.src);
      group.candidates.forEach((targetCandidate) => {
        unmarkQueued(targetCandidate.el);
        setState(targetCandidate.el, "error");
        failedAt.set(targetCandidate.el, Date.now());
        targetCandidate.el.title = "BTA MangaTranslate: translation timed out, will retry automatically.";
      });
      group.resolvers.forEach(({ resolve: groupResolve }) => groupResolve(false));
      finish(false);
      if (isAutoTranslateActive()) scheduleAutoTranslate(600);
    }, TRANSLATION_TIMEOUT_MS);

    group.resolvers.push({ candidate, resolve });
    chrome.runtime.sendMessage({
      type: "bta-translate-image",
      sessionId,
      src: candidate.src,
      sourceLang: settings.sourceLang,
      targetLang: settings.targetLang,
      fastMode: settings.fastMode,
      renderMode: "bubbles",
      fontFamily: settings.fontFamily,
      fontSize: settings.fontSize,
      slangAdaptation: settings.slangAdaptation
    }, (response) => {
      if (settled) return;
      if (group.sessionId !== translationSessionId) {
        pendingTranslationGroups.delete(candidate.src);
        activeTranslations.delete(candidate.src);
        group.candidates.forEach((targetCandidate) => {
          unmarkQueued(targetCandidate.el);
          setState(targetCandidate.el, "idle");
        });
        group.resolvers.forEach(({ resolve }) => resolve(false));
        finish(false);
        return;
      }
      if (chrome.runtime.lastError) {
        pendingTranslationGroups.delete(candidate.src);
        activeTranslations.delete(candidate.src);
        group.candidates.forEach((targetCandidate) => {
          unmarkQueued(targetCandidate.el);
          setState(targetCandidate.el, "error");
          failedAt.set(targetCandidate.el, Date.now());
          targetCandidate.el.title = `BTA MangaTranslate: ${chrome.runtime.lastError.message || "extension message failed"}`;
        });
        group.resolvers.forEach(({ resolve }) => resolve(false));
        finish(false);
        if (isAutoTranslateActive()) scheduleAutoTranslate(800);
        return;
      }
      pendingTranslationGroups.delete(candidate.src);
      activeTranslations.delete(candidate.src);
      if (!response?.ok) {
        const cancelled = isTabCancelError(response?.error);
        group.candidates.forEach((targetCandidate) => {
          unmarkQueued(targetCandidate.el);
          setState(targetCandidate.el, cancelled ? "idle" : "error");
          if (cancelled) {
            failedAt.delete(targetCandidate.el);
          } else {
            failedAt.set(targetCandidate.el, Date.now());
          }
          targetCandidate.el.title = `BTA MangaTranslate: ${response?.error || "translation failed"}`;
        });
        group.resolvers.forEach(({ resolve }) => resolve(false));
        finish(false);
        if (!cancelled && isAutoTranslateActive()) scheduleAutoTranslate(900);
        return;
      }
      if (response.mode === "text_overlay") {
        group.candidates.forEach((targetCandidate) => {
          unmarkQueued(targetCandidate.el);
          setState(targetCandidate.el, "error");
          failedAt.set(targetCandidate.el, Date.now());
          targetCandidate.el.title = "BTA MangaTranslate: backend returned text only; bubble overlays are required.";
        });
        group.resolvers.forEach(({ resolve }) => resolve(false));
        finish(false);
        if (isAutoTranslateActive()) scheduleAutoTranslate(900);
        return;
      }

      rememberTranslatedResponse(candidate.src, response);
      group.candidates.forEach((targetCandidate) => {
        unmarkQueued(targetCandidate.el);
        const ok = applyBubbleTranslations(targetCandidate, response);
        if (!ok) {
          setState(targetCandidate.el, "error");
          failedAt.set(targetCandidate.el, Date.now());
          targetCandidate.el.title = "BTA MangaTranslate: no translated bubbles returned.";
          if (isAutoTranslateActive()) scheduleAutoTranslate(900);
          return;
        }
        markTranslated(targetCandidate);
        failedAt.delete(targetCandidate.el);
        setState(targetCandidate.el, responseHasPendingBubbles(response) ? "partial" : "done");
        targetCandidate.el.title = responseHasPendingBubbles(response)
          ? "BTA MangaTranslate: traducao parcial. Os baloes traduzidos foram preservados."
          : "";
      });
      group.resolvers.forEach(({ candidate: resolverCandidate, resolve }) => {
        resolve(translated.has(resolverCandidate.el));
      });
      finish(translated.has(candidate.el));
      return;
    });
  });
}

function autoCandidateRank(candidate) {
  const viewportTop = window.scrollY;
  const viewportBottom = viewportTop + window.innerHeight;
  const bottom = candidate.top + candidate.rect.height;
  if (bottom < viewportTop) return 2;
  if (candidate.top <= viewportBottom) return 0;
  return 1;
}

function isInAutoPrefetchWindow(candidate) {
  const viewportTop = window.scrollY;
  const viewportBottom = viewportTop + window.innerHeight;
  const bottom = candidate.top + candidate.rect.height;
  return bottom >= viewportTop - AUTO_PREFETCH_BEHIND_PX
    && candidate.top <= viewportBottom + AUTO_PREFETCH_AHEAD_PX;
}

function isAutoPriorityCandidate(candidate) {
  return autoCandidateRank(candidate) === 0 || isInAutoPrefetchWindow(candidate);
}

function pendingAutoBackgroundCount() {
  let count = 0;
  pendingTranslationGroups.forEach((group) => {
    const candidates = [...(group.candidates || [])];
    if (!candidates.some(isAutoPriorityCandidate)) count += 1;
  });
  return count;
}

function collectCandidates({ visibleOnly = false, prioritizeViewport = false, ignoreFailure = false } = {}) {
  const seenSources = new Set();
  return [...document.querySelectorAll(CANDIDATE_SELECTOR)]
    .map((el) => candidateFromElement(el, { visibleOnly, ignoreFailure }))
    .filter(Boolean)
    .filter((candidate) => {
      if (!candidate.src) return true;
      if (seenSources.has(candidate.src) && !translatedResponses.has(candidate.src)) return false;
      seenSources.add(candidate.src);
      return true;
    })
    .sort((a, b) => {
      if (prioritizeViewport) {
        const rankDelta = autoCandidateRank(a) - autoCandidateRank(b);
        if (rankDelta) return rankDelta;
      }
      return (a.top - b.top) || (a.left - b.left);
    });
}

function collectAutoCandidates() {
  const now = Date.now();
  const seen = new Set();
  const merged = [];
  const add = (items) => {
    items.forEach((candidate) => {
      if (!candidate?.src || seen.has(candidate.src)) return;
      const lastAttempt = autoAttemptedAtBySrc.get(candidate.src) || 0;
      if (now - lastAttempt < AUTO_RETRY_COOLDOWN_MS) return;
      seen.add(candidate.src);
      merged.push(candidate);
    });
  };
  add(collectCandidates({ visibleOnly: true, prioritizeViewport: true, ignoreFailure: true }));
  add(collectCandidates({ visibleOnly: false, prioritizeViewport: true, ignoreFailure: true }).filter(isInAutoPrefetchWindow));
  add(collectCandidates({ visibleOnly: false, prioritizeViewport: true, ignoreFailure: true }));
  while (autoAttemptedAtBySrc.size > 600) {
    autoAttemptedAtBySrc.delete(autoAttemptedAtBySrc.keys().next().value);
  }
  return merged;
}

function runAutoTranslateTick() {
  if (!isAutoTranslateActive()) return;
  observeAutoTranslateTargets();
  const slots = Math.max(0, AUTO_BATCH_LIMIT - pendingTranslationGroups.size);
  if (!slots) return;
  const allCandidates = collectAutoCandidates();
  const priorityCandidates = allCandidates.filter(isAutoPriorityCandidate);
  const backgroundCandidates = allCandidates.filter((candidate) => !isAutoPriorityCandidate(candidate));
  const backgroundLimit = priorityCandidates.length ? AUTO_BACKGROUND_BATCH_LIMIT : AUTO_IDLE_BACKGROUND_BATCH_LIMIT;
  const backgroundSlots = Math.max(0, backgroundLimit - pendingAutoBackgroundCount());
  const candidates = [
    ...priorityCandidates.slice(0, slots),
    ...backgroundCandidates.slice(0, Math.min(backgroundSlots, Math.max(0, slots - priorityCandidates.length)))
  ].slice(0, slots);
  candidates.forEach((candidate) => {
    autoAttemptedAtBySrc.set(candidate.src, Date.now());
    failedAt.delete(candidate.el);
    translateCandidate(candidate).catch(() => {});
  });
}

async function translateCandidatesFast(candidates, delayMs = 60) {
  let next = 0;
  let count = 0;
  let attempted = 0;
  const workerCount = Math.max(1, Math.min(TRANSLATION_CONCURRENCY, candidates.length));

  async function worker() {
    while (!tabTranslationCancelled) {
      const index = next;
      next += 1;
      if (index >= candidates.length) break;
      const candidate = candidates[index];
      attempted += 1;
      const ok = await translateCandidate(candidate);
      if (ok) count += 1;
      if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return { count, attempted };
}

async function translatePage({ visibleOnly = false, limit = Infinity, prioritizeViewport = false, ignoreFailure = false } = {}) {
  if (queueRunning) {
    if (isAutoTranslateActive()) pendingAutoRun = true;
    return 0;
  }
  queueRunning = true;
  tabTranslationCancelled = false;
  let count = 0;
  let attempted = 0;
  try {
    const candidates = collectCandidates({ visibleOnly, prioritizeViewport, ignoreFailure }).slice(0, limit);
    const result = await translateCandidatesFast(candidates, 60);
    count = result.count;
    attempted = result.attempted;
  } finally {
    queueRunning = false;
    if (pendingAutoRun && isAutoTranslateActive()) {
      pendingAutoRun = false;
      scheduleAutoTranslate(350);
    } else if (isAutoTranslateActive() && attempted > 0) {
      scheduleAutoTranslate(450);
    }
  }
  return count;
}

async function translateCurrentVisible() {
  if (queueRunning) return { count: 0, error: "TraduÃ§Ã£o em andamento. Aguarde terminar." };
  const candidates = collectCandidates({ visibleOnly: true });
  if (!candidates[0]) return { count: 0, error: "Nenhuma imagem grande visÃ­vel" };

  queueRunning = true;
  tabTranslationCancelled = false;
  try {
    let lastError = "Falha ao traduzir imagem visÃ­vel";
    const visibleCandidates = candidates.slice(0, 8);
    const result = await translateCandidatesFast(visibleCandidates, 40);
    const count = result.count;
    visibleCandidates.forEach((candidate) => {
      lastError = candidate.el.title || lastError;
    });
    return count ? { count } : { count: 0, error: lastError };
  } finally {
    queueRunning = false;
  }
}

function scheduleAutoTranslate(delayMs = 700) {
  window.clearTimeout(autoTimer);
  autoTimer = window.setTimeout(() => {
    runAutoTranslateTick();
  }, delayMs);
}

function createButton(img) {
  if (buttonTargets.has(img)) return;
  buttonTargets.add(img);

  const button = document.createElement("button");
  button.className = "bta-hover-button";
  button.textContent = "BTA Translate";
  button.title = "Translate this image with BTA MangaTranslate";
  Object.assign(button.style, {
    position: "fixed",
    zIndex: "2147483647",
    display: "none",
    border: "0",
    borderRadius: "4px",
    background: "#e11d48",
    color: "#fff",
    font: "700 12px Arial, sans-serif",
    padding: "7px 9px",
    boxShadow: "0 2px 8px rgba(0,0,0,.25)",
    cursor: "pointer"
  });
  document.documentElement.append(button);

  function place() {
    const rect = img.getBoundingClientRect();
    button.style.left = `${rect.left + 8}px`;
    button.style.top = `${rect.top + 8}px`;
  }

  img.addEventListener("mouseenter", () => {
    if (!isCandidate(img)) return;
    place();
    button.style.display = "block";
  });
  img.addEventListener("mouseleave", () => {
    setTimeout(() => {
      if (!button.matches(":hover")) button.style.display = "none";
    }, 80);
  });
  img.addEventListener("load", () => {
    reflowBubbleOverlays();
    if (isAutoTranslateActive()) {
      scheduleAutoTranslate(0);
    }
  });
  button.addEventListener("mouseleave", () => {
    button.style.display = "none";
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    translateImage(img);
  });
  window.addEventListener("scroll", () => {
    if (button.style.display !== "none") place();
  }, { passive: true });
  window.addEventListener("resize", () => {
    if (button.style.display !== "none") place();
  });
}

function installButtons() {
  for (const img of document.images) createButton(img);
  document.querySelectorAll("canvas, [style*='background-image']").forEach((el) => {
    if (candidateFromElement(el, { visibleOnly: true })) createButton(el);
  });
  observeAutoTranslateTargets();
}

function observeAutoTranslateTargets() {
  if (!("IntersectionObserver" in window)) return;
  if (!autoViewportObserver) {
    autoViewportObserver = new IntersectionObserver((entries) => {
      if (!isAutoTranslateActive()) return;
      if (entries.some((entry) => entry.isIntersecting || entry.intersectionRatio > 0)) {
        scheduleAutoTranslate(0);
      }
    }, { root: null, rootMargin: `${AUTO_PREFETCH_BEHIND_PX}px 0px ${AUTO_PREFETCH_AHEAD_PX}px 0px`, threshold: 0.01 });
  }
  document.querySelectorAll(CANDIDATE_SELECTOR).forEach((el) => {
    if (autoObservedTargets.has(el)) return;
    autoObservedTargets.add(el);
    autoViewportObserver.observe(el);
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "bta-settings") {
    const wasAutoTranslateActive = isAutoTranslateActive();
    settings = { ...settings, ...message.settings };
    if (!message.liveOnly && Object.prototype.hasOwnProperty.call(message.settings || {}, "autoTranslate")) {
      autoTranslateSession = Boolean(settings.autoTranslate);
      if (!autoTranslateSession) {
        cancelLocalTranslationSession();
      } else {
        tabTranslationCancelled = false;
        autoAttemptedAtBySrc.clear();
      }
    }
    applyRenderSettings();
    reflowBubbleOverlays();
    if (!message.liveOnly && isAutoTranslateActive() && !wasAutoTranslateActive) {
      scheduleAutoTranslate(0);
    }
    sendResponse({ ok: true });
  }
  if (message?.type === "bta-bubble-stream") {
    handleBubbleStreamEvent(message.src, message.event);
    sendResponse({ ok: true });
  }
  if (message?.type === "bta-translate-visible") {
    if (message.settings) settings = { ...settings, ...message.settings };
    applyRenderSettings();
    reflowBubbleOverlays();
    translatePage({ visibleOnly: true }).then((count) => sendResponse({ count }));
    return true;
  }
  if (message?.type === "bta-translate-current-visible") {
    if (message.settings) settings = { ...settings, ...message.settings };
    applyRenderSettings();
    reflowBubbleOverlays();
    translateCurrentVisible().then((result) => sendResponse(result));
    return true;
  }
  if (message?.type === "bta-reset-page") {
    resetPageTranslations();
    sendResponse({ ok: true });
    return true;
  }
});

function handlePageUrlChange() {
  if (location.href === currentPageUrl) return;
  currentPageUrl = location.href;
  translationSessionId += 1;
  resetPageTranslations({ preserveAuto: true });
  window.setTimeout(() => {
    installButtons();
    if (isAutoTranslateActive()) scheduleAutoTranslate(0);
  }, 250);
}

["pushState", "replaceState"].forEach((methodName) => {
  const original = history[methodName];
  history[methodName] = function patchedHistoryMethod(...args) {
    const result = original.apply(this, args);
    window.setTimeout(handlePageUrlChange, 0);
    return result;
  };
});

window.addEventListener("popstate", handlePageUrlChange);
window.addEventListener("hashchange", handlePageUrlChange);
window.addEventListener("pagehide", () => cancelLocalTranslationSession());
window.setInterval(handlePageUrlChange, 1000);

function isOwnMutation(mutation) {
  const nodes = [...mutation.addedNodes, ...mutation.removedNodes].filter((node) => node.nodeType === Node.ELEMENT_NODE);
  return nodes.length > 0 && nodes.every((node) => (
    node.classList?.contains("bta-bubble-layer")
    || node.classList?.contains("bta-bubble-text")
    || node.classList?.contains("bta-hover-button")
    || node.classList?.contains("bta-translation-overlay")
    || node.closest?.(".bta-bubble-layer, .bta-translation-overlay")
    || node.textContent === "BTA Translate"
  ));
}

function scheduleDomRefresh() {
  window.clearTimeout(domRefreshTimer);
  domRefreshTimer = window.setTimeout(() => {
    installButtons();
    reflowBubbleOverlays();
    if (isAutoTranslateActive()) {
      scheduleAutoTranslate(0);
    }
  }, 400);
}

const observer = new MutationObserver((mutations) => {
  if (mutations.length && mutations.every(isOwnMutation)) return;
  scheduleDomRefresh();
});
observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["src", "srcset", "data-src", "data-srcset", "data-original", "data-original-src", "data-lazy-src", "data-lazy", "data-image", "data-full", "data-url", "data-cfsrc", "style", "class"]
});

function handleAnyScroll() {
  scheduleBubbleOverlayReflow();
  if (isAutoTranslateActive()) {
    scheduleAutoTranslate(0);
  }
}

window.addEventListener("scroll", handleAnyScroll, { passive: true });
document.addEventListener("scroll", handleAnyScroll, { passive: true, capture: true });

window.addEventListener("resize", () => {
  scheduleBubbleOverlayReflow();
  if (isAutoTranslateActive()) {
    scheduleAutoTranslate(0);
  }
});

document.addEventListener("load", (event) => {
  if (!(event.target instanceof HTMLImageElement)) return;
  installButtons();
  scheduleBubbleOverlayReflow();
  if (isAutoTranslateActive()) {
    scheduleAutoTranslate(0);
  }
}, true);

window.setInterval(() => {
  if (!isAutoTranslateActive()) return;
  observeAutoTranslateTargets();
  scheduleAutoTranslate(80);
}, AUTO_HEARTBEAT_MS);

const style = document.createElement("style");
style.textContent = `
  .bta-bubble-layer {
    position: absolute;
    left: 0;
    top: 0;
    width: 0;
    height: 0;
    z-index: 2147483646;
    pointer-events: none;
    overflow: visible;
  }
  .bta-bubble-text {
    position: absolute;
    box-sizing: border-box;
    padding: 0;
    overflow: visible;
    box-shadow: none;
    mix-blend-mode: normal;
    background: transparent;
  }
  .bta-bubble-fill {
    position: absolute;
    inset: 0;
    box-sizing: border-box;
    z-index: 0;
    pointer-events: none;
  }
  .bta-bubble-copy {
    position: absolute;
    box-sizing: border-box;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: normal;
    overflow: hidden;
    transform-origin: center center;
    line-height: 1.12;
    font-weight: 800;
    letter-spacing: 0;
    hyphens: auto;
    -webkit-font-smoothing: antialiased;
  }
  .bta-bubble-text.bta-bubble-pending {
    opacity: 0;
  }
  .bta-translation-overlay {
    max-width: min(100%, 900px);
    margin: 12px auto;
    border: 1px solid rgba(244, 63, 94, .55);
    border-radius: 10px;
    background: #08080b;
    color: #f8f8fb;
    box-shadow: 0 0 22px rgba(244, 63, 94, .35);
    font-family: Inter, Segoe UI, Arial, sans-serif;
    overflow: hidden;
  }
  .bta-translation-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid #282833;
    background: linear-gradient(90deg, rgba(225, 29, 72, .24), rgba(8, 8, 11, .96));
  }
  .bta-translation-head strong {
    color: #fff;
    font-size: 13px;
  }
  .bta-translation-head button {
    border: 1px solid #3a3d48;
    border-radius: 5px;
    background: transparent;
    color: #fff;
    cursor: pointer;
    width: 24px;
    height: 24px;
  }
  .bta-translation-body {
    white-space: pre-wrap;
    padding: 14px;
    color: #fff;
    font-size: 12px;
    line-height: 1.45;
    font-weight: 800;
  }
  .bta-translation-source {
    border-top: 1px solid #1d1d26;
    color: #8c8fa3;
    font-size: 12px;
    padding: 8px 12px 12px;
  }
  .bta-translation-source pre {
    white-space: pre-wrap;
    margin: 8px 0 0;
    color: #c8cee0;
  }
`;
document.documentElement.append(style);


}

