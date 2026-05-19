const SERVER = "http://localhost:8000";

const TRANSLATION_LANGUAGES = [
  { value: "Auto" },
  { value: "Arabic", code: "ar" },
  { value: "Bengali", code: "bn" },
  { value: "Bulgarian", code: "bg" },
  { value: "Chinese (Simplified)", code: "zh-Hans" },
  { value: "Chinese (Traditional)", code: "zh-Hant" },
  { value: "Czech", code: "cs" },
  { value: "Danish", code: "da" },
  { value: "Dutch", code: "nl" },
  { value: "English", code: "en" },
  { value: "Filipino", code: "fil" },
  { value: "Finnish", code: "fi" },
  { value: "French", code: "fr" },
  { value: "German", code: "de" },
  { value: "Greek", code: "el" },
  { value: "Hebrew", code: "he" },
  { value: "Hindi", code: "hi" },
  { value: "Hungarian", code: "hu" },
  { value: "Indonesian", code: "id" },
  { value: "Italian", code: "it" },
  { value: "Japanese", code: "ja" },
  { value: "Korean", code: "ko" },
  { value: "Malay", code: "ms" },
  { value: "Norwegian", code: "no" },
  { value: "Persian", code: "fa" },
  { value: "Polish", code: "pl" },
  { value: "Portuguese", code: "pt" },
  { value: "Portuguese (Brazil)", code: "pt-BR" },
  { value: "Romanian", code: "ro" },
  { value: "Russian", code: "ru" },
  { value: "Spanish", code: "es" },
  { value: "Swedish", code: "sv" },
  { value: "Thai", code: "th" },
  { value: "Turkish", code: "tr" },
  { value: "Ukrainian", code: "uk" },
  { value: "Urdu", code: "ur" },
  { value: "Vietnamese", code: "vi" }
];

const LANGUAGE_ALIASES = {
  "Bahasa Indonesia": "Indonesian",
  "Portuguese (BR)": "Portuguese (Brazil)",
  "Portuguese (Brazilian)": "Portuguese (Brazil)"
};

const LANGUAGE_VALUES = new Set(TRANSLATION_LANGUAGES.map((lang) => lang.value));

const UI_TEXT = {
  pt: {
    htmlLang: "pt-BR",
    poweredBy: "por BTA Studio",
    uiLanguageTitle: "Idioma da interface",
    navLabel: "Navegação do popup",
    tabTranslate: "TRADUZIR",
    tabTools: "FERRAMENTAS",
    tabSettings: "AJUSTES",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "TRADUÇÃO DE IDIOMA",
    sourceLabel: "ORIGEM",
    targetLabel: "DESTINO",
    swapTitle: "Inverter idiomas",
    sectionAi: "INTELIGÊNCIA ARTIFICIAL",
    autoTitle: "Auto-Tradução de Páginas",
    autoDesc: "Traduzir novas páginas automaticamente",
    fastTitle: "Modo Rápido",
    fastDesc: "Pula análise contextual para responder mais rápido",
    translateButton: "TRADUZIR PÁGINA ATUAL",
    sessionWaiting: "Sessão atual: aguardando",
    resetPage: "Resetar Página",
    snipTitle: "Recortar Área",
    snipDesc: "Snip & Ask AI",
    paintTitle: "Pintura Manual",
    paintDesc: "Apagar texto",
    sectionStyles: "ESTILOS GLOBAIS DE RENDERIZAÇÃO",
    fontSizeLabel: "Escala da Fonte",
    outlineSizeLabel: "Tamanho do Contorno",
    opacityLabel: "Opacidade do Balão",
    fontFamilyLabel: "Família da Fonte",
    sectionProvider: "MOTOR DE TRADUÇÃO AI",
    engineLabel: "Motor de Tradução Ativo",
    engineBta: "BTA Engine Ultra v2.5 (Recomendado)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "Modo de Adaptação de Gírias",
    adaptFaithful: "Fiel ao Contexto Ocidental",
    adaptLiteral: "Literal",
    adaptNatural: "Natural Brasileiro",
    sectionSystem: "SISTEMA E ATALHOS",
    shortcutLabel: "Atalho de Tradução Instantânea",
    exportConfig: "Exportar Configurações",
    backupButton: "Fazer Backup",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "Servidor: não verificado",
    checking: "Verificando servidor local...",
    serverReady: "Servidor: pronto em localhost:8000",
    serverMissing: "Servidor: inicie run.bat primeiro",
    sending: "Enviando imagens visíveis...",
    translatingVisible: "Traduzindo imagem visível...",
    queued: (count) => `Sessão atual: ${count} imagem(ns) enviada(s)`,
    empty: "Nenhuma imagem grande visível",
    resetHint: "Recarregue a página para restaurar imagens originais.",
    snipHint: "Recorte manual ainda será conectado ao content script.",
    paintHint: "Pintura manual ainda será conectada ao content script.",
    backupHint: "Configurações salvas no Chrome Sync.",
    helpHint: "Ajuda: mantenha run.bat aberto e recarregue a extensão após alterações.",
    autoLang: "Automático",
    indonesianLabel: "Bahasa Indonesia"
  },
  en: {
    htmlLang: "en",
    poweredBy: "powered by BTA Studio",
    uiLanguageTitle: "Interface language",
    navLabel: "Popup navigation",
    tabTranslate: "TRANSLATE",
    tabTools: "TOOLS",
    tabSettings: "SETTINGS",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "LANGUAGE TRANSLATION",
    sourceLabel: "FROM",
    targetLabel: "TO",
    swapTitle: "Swap languages",
    sectionAi: "ARTIFICIAL INTELLIGENCE",
    autoTitle: "Page Auto-Translation",
    autoDesc: "Translate new pages automatically",
    fastTitle: "Fast Mode",
    fastDesc: "Skip contextual analysis for faster replies",
    translateButton: "TRANSLATE CURRENT PAGE",
    sessionWaiting: "Current session: waiting",
    resetPage: "Reset Page",
    snipTitle: "Snip Area",
    snipDesc: "Snip & Ask AI",
    paintTitle: "Manual Paint",
    paintDesc: "Erase text",
    sectionStyles: "GLOBAL RENDERING STYLES",
    fontSizeLabel: "Font Scale",
    outlineSizeLabel: "Outline Size",
    opacityLabel: "Balloon Opacity",
    fontFamilyLabel: "Font Family",
    sectionProvider: "AI TRANSLATION PROVIDER",
    engineLabel: "Active Translation Engine",
    engineBta: "BTA Engine Ultra v2.5 (Recommended)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "Slang Adaptation Mode",
    adaptFaithful: "Faithful to Western Context",
    adaptLiteral: "Literal",
    adaptNatural: "Natural Brazilian",
    sectionSystem: "SYSTEM AND SHORTCUTS",
    shortcutLabel: "Instant Translation Shortcut",
    exportConfig: "Export Settings",
    backupButton: "Make Backup",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "Server: not checked",
    checking: "Checking local server...",
    serverReady: "Server: ready on localhost:8000",
    serverMissing: "Server: start run.bat first",
    sending: "Sending visible images...",
    translatingVisible: "Translating visible image...",
    queued: (count) => `Current session: ${count} image(s) queued`,
    empty: "No large visible image found",
    resetHint: "Reload the page to restore original images.",
    snipHint: "Manual snip will be connected to the content script.",
    paintHint: "Manual paint will be connected to the content script.",
    backupHint: "Settings saved to Chrome Sync.",
    helpHint: "Help: keep run.bat open and reload the extension after changes.",
    autoLang: "Auto",
    indonesianLabel: "Bahasa Indonesia"
  },
  ja: {
    htmlLang: "ja",
    poweredBy: "BTA Studio 提供",
    uiLanguageTitle: "インターフェース言語",
    navLabel: "ポップアップナビゲーション",
    tabTranslate: "翻訳",
    tabTools: "ツール",
    tabSettings: "設定",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "言語翻訳",
    sourceLabel: "原文",
    targetLabel: "翻訳先",
    swapTitle: "言語を入れ替え",
    sectionAi: "人工知能",
    autoTitle: "ページ自動翻訳",
    autoDesc: "新しいページを自動で翻訳",
    fastTitle: "高速モード",
    fastDesc: "文脈分析を省いて高速化",
    translateButton: "現在のページを翻訳",
    sessionWaiting: "現在のセッション: 待機中",
    resetPage: "ページをリセット",
    snipTitle: "範囲を切り取る",
    snipDesc: "Snip & Ask AI",
    paintTitle: "手動ペイント",
    paintDesc: "テキストを消去",
    sectionStyles: "レンダリングスタイル",
    fontSizeLabel: "フォント倍率",
    opacityLabel: "吹き出しの不透明度",
    fontFamilyLabel: "フォント",
    sectionProvider: "AI翻訳プロバイダー",
    engineLabel: "有効な翻訳エンジン",
    engineBta: "BTA Engine Ultra v2.5 (推奨)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "スラング適応モード",
    adaptFaithful: "西洋文脈に忠実",
    adaptLiteral: "直訳",
    adaptNatural: "自然なブラジル表現",
    sectionSystem: "システムとショートカット",
    shortcutLabel: "即時翻訳ショートカット",
    exportConfig: "設定をエクスポート",
    backupButton: "バックアップ",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "サーバー: 未確認",
    checking: "ローカルサーバーを確認中...",
    serverReady: "サーバー: localhost:8000 準備完了",
    serverMissing: "サーバー: 先に run.bat を起動してください",
    sending: "表示中の画像を送信中...",
    translatingVisible: "表示中の画像を翻訳中...",
    queued: (count) => `現在のセッション: ${count} 件送信`,
    empty: "大きな表示画像が見つかりません",
    resetHint: "元の画像に戻すにはページを再読み込みしてください。",
    snipHint: "手動切り取りは content script に接続予定です。",
    paintHint: "手動ペイントは content script に接続予定です。",
    backupHint: "設定を Chrome Sync に保存しました。",
    helpHint: "ヘルプ: run.bat を開いたままにし、変更後に拡張機能を再読み込みしてください。",
    autoLang: "自動",
    indonesianLabel: "Bahasa Indonesia"
  },
  ko: {
    htmlLang: "ko",
    poweredBy: "BTA Studio 제공",
    uiLanguageTitle: "인터페이스 언어",
    navLabel: "팝업 내비게이션",
    tabTranslate: "번역",
    tabTools: "도구",
    tabSettings: "설정",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "언어 번역",
    sourceLabel: "원본",
    targetLabel: "대상",
    swapTitle: "언어 전환",
    sectionAi: "인공지능",
    autoTitle: "페이지 자동 번역",
    autoDesc: "새 페이지를 자동으로 번역",
    fastTitle: "빠른 모드",
    fastDesc: "문맥 분석을 건너뛰어 더 빠르게 응답",
    translateButton: "현재 페이지 번역",
    sessionWaiting: "현재 세션: 대기 중",
    resetPage: "페이지 초기화",
    snipTitle: "영역 자르기",
    snipDesc: "Snip & Ask AI",
    paintTitle: "수동 페인트",
    paintDesc: "텍스트 지우기",
    sectionStyles: "전역 렌더링 스타일",
    fontSizeLabel: "글꼴 배율",
    opacityLabel: "말풍선 불투명도",
    fontFamilyLabel: "글꼴",
    sectionProvider: "AI 번역 제공자",
    engineLabel: "활성 번역 엔진",
    engineBta: "BTA Engine Ultra v2.5 (추천)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "속어 적용 모드",
    adaptFaithful: "서구 문맥에 충실",
    adaptLiteral: "직역",
    adaptNatural: "자연스러운 브라질식",
    sectionSystem: "시스템 및 단축키",
    shortcutLabel: "즉시 번역 단축키",
    exportConfig: "설정 내보내기",
    backupButton: "백업 만들기",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "서버: 확인 안 됨",
    checking: "로컬 서버 확인 중...",
    serverReady: "서버: localhost:8000 준비됨",
    serverMissing: "서버: 먼저 run.bat을 실행하세요",
    sending: "보이는 이미지를 보내는 중...",
    translatingVisible: "보이는 이미지 번역 중...",
    queued: (count) => `현재 세션: 이미지 ${count}개 전송됨`,
    empty: "큰 표시 이미지가 없습니다",
    resetHint: "원본 이미지를 복원하려면 페이지를 새로고침하세요.",
    snipHint: "수동 자르기는 content script에 연결될 예정입니다.",
    paintHint: "수동 페인트는 content script에 연결될 예정입니다.",
    backupHint: "설정이 Chrome Sync에 저장되었습니다.",
    helpHint: "도움말: run.bat을 열어 둔 상태에서 변경 후 확장 프로그램을 새로고침하세요.",
    autoLang: "자동",
    indonesianLabel: "Bahasa Indonesia"
  },
  es: {
    htmlLang: "es",
    poweredBy: "por BTA Studio",
    uiLanguageTitle: "Idioma de la interfaz",
    navLabel: "Navegación del popup",
    tabTranslate: "TRADUCIR",
    tabTools: "HERRAMIENTAS",
    tabSettings: "AJUSTES",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "TRADUCCIÓN DE IDIOMA",
    sourceLabel: "ORIGEN",
    targetLabel: "DESTINO",
    swapTitle: "Invertir idiomas",
    sectionAi: "INTELIGENCIA ARTIFICIAL",
    autoTitle: "Traducción Automática",
    autoDesc: "Traducir páginas nuevas automáticamente",
    fastTitle: "Modo Rápido",
    fastDesc: "Omite análisis contextual para responder más rápido",
    translateButton: "TRADUCIR PÁGINA ACTUAL",
    sessionWaiting: "Sesión actual: esperando",
    resetPage: "Restablecer Página",
    snipTitle: "Recortar Área",
    snipDesc: "Snip & Ask AI",
    paintTitle: "Pintura Manual",
    paintDesc: "Borrar texto",
    sectionStyles: "ESTILOS GLOBALES DE RENDERIZADO",
    fontSizeLabel: "Escala de Fuente",
    opacityLabel: "Opacidad del Globo",
    fontFamilyLabel: "Familia de Fuente",
    sectionProvider: "MOTOR DE TRADUCCIÓN AI",
    engineLabel: "Motor de Traducción Activo",
    engineBta: "BTA Engine Ultra v2.5 (Recomendado)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "Modo de Adaptación de Jerga",
    adaptFaithful: "Fiel al Contexto Occidental",
    adaptLiteral: "Literal",
    adaptNatural: "Natural Brasileño",
    sectionSystem: "SISTEMA Y ATAJOS",
    shortcutLabel: "Atajo de Traducción Instantánea",
    exportConfig: "Exportar Configuración",
    backupButton: "Hacer Backup",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "Servidor: no verificado",
    checking: "Verificando servidor local...",
    serverReady: "Servidor: listo en localhost:8000",
    serverMissing: "Servidor: inicia run.bat primero",
    sending: "Enviando imágenes visibles...",
    translatingVisible: "Traduciendo imagen visible...",
    queued: (count) => `Sesión actual: ${count} imagen(es) enviadas`,
    empty: "No hay imagen grande visible",
    resetHint: "Recarga la página para restaurar las imágenes originales.",
    snipHint: "El recorte manual todavía se conectará al content script.",
    paintHint: "La pintura manual todavía se conectará al content script.",
    backupHint: "Configuración guardada en Chrome Sync.",
    helpHint: "Ayuda: mantén run.bat abierto y recarga la extensión tras los cambios.",
    autoLang: "Auto",
    indonesianLabel: "Bahasa Indonesia"
  },
  fr: {
    htmlLang: "fr",
    poweredBy: "par BTA Studio",
    uiLanguageTitle: "Langue de l'interface",
    navLabel: "Navigation du popup",
    tabTranslate: "TRADUIRE",
    tabTools: "OUTILS",
    tabSettings: "RÉGLAGES",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "TRADUCTION DE LANGUE",
    sourceLabel: "SOURCE",
    targetLabel: "CIBLE",
    swapTitle: "Inverser les langues",
    sectionAi: "INTELLIGENCE ARTIFICIELLE",
    autoTitle: "Traduction Automatique",
    autoDesc: "Traduire automatiquement les nouvelles pages",
    fastTitle: "Mode Rapide",
    fastDesc: "Ignore l'analyse contextuelle pour répondre plus vite",
    translateButton: "TRADUIRE LA PAGE ACTUELLE",
    sessionWaiting: "Session actuelle : en attente",
    resetPage: "Réinitialiser",
    snipTitle: "Découper Zone",
    snipDesc: "Snip & Ask AI",
    paintTitle: "Peinture Manuelle",
    paintDesc: "Effacer le texte",
    sectionStyles: "STYLES GLOBAUX DE RENDU",
    fontSizeLabel: "Échelle de Police",
    opacityLabel: "Opacité de Bulle",
    fontFamilyLabel: "Famille de Police",
    sectionProvider: "FOURNISSEUR DE TRADUCTION AI",
    engineLabel: "Moteur de Traduction Actif",
    engineBta: "BTA Engine Ultra v2.5 (Recommandé)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "Mode d'Adaptation de l'Argot",
    adaptFaithful: "Fidèle au Contexte Occidental",
    adaptLiteral: "Littéral",
    adaptNatural: "Brésilien Naturel",
    sectionSystem: "SYSTÈME ET RACCOURCIS",
    shortcutLabel: "Raccourci de Traduction Instantanée",
    exportConfig: "Exporter les Réglages",
    backupButton: "Faire Backup",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "Serveur : non vérifié",
    checking: "Vérification du serveur local...",
    serverReady: "Serveur : prêt sur localhost:8000",
    serverMissing: "Serveur : lancez d'abord run.bat",
    sending: "Envoi des images visibles...",
    translatingVisible: "Traduction de l'image visible...",
    queued: (count) => `Session actuelle : ${count} image(s) envoyée(s)`,
    empty: "Aucune grande image visible",
    resetHint: "Rechargez la page pour restaurer les images originales.",
    snipHint: "Le découpage manuel sera connecté au content script.",
    paintHint: "La peinture manuelle sera connectée au content script.",
    backupHint: "Réglages enregistrés dans Chrome Sync.",
    helpHint: "Aide : gardez run.bat ouvert et rechargez l'extension après les modifications.",
    autoLang: "Auto",
    indonesianLabel: "Bahasa Indonesia"
  },
  id: {
    htmlLang: "id",
    poweredBy: "oleh BTA Studio",
    uiLanguageTitle: "Bahasa antarmuka",
    navLabel: "Navigasi popup",
    tabTranslate: "TERJEMAH",
    tabTools: "ALAT",
    tabSettings: "PENGATURAN",
    health: "GitHub",
    healthTitle: "GitHub",
    sectionLanguage: "TERJEMAHAN BAHASA",
    sourceLabel: "ASAL",
    targetLabel: "TUJUAN",
    swapTitle: "Tukar bahasa",
    sectionAi: "KECERDASAN BUATAN",
    autoTitle: "Terjemahan Otomatis Halaman",
    autoDesc: "Terjemahkan halaman baru secara otomatis",
    fastTitle: "Mode Cepat",
    fastDesc: "Lewati analisis konteks agar lebih cepat",
    translateButton: "TERJEMAHKAN HALAMAN INI",
    sessionWaiting: "Sesi saat ini: menunggu",
    resetPage: "Reset Halaman",
    snipTitle: "Potong Area",
    snipDesc: "Snip & Ask AI",
    paintTitle: "Lukis Manual",
    paintDesc: "Hapus teks",
    sectionStyles: "GAYA RENDER GLOBAL",
    fontSizeLabel: "Skala Font",
    opacityLabel: "Opasitas Balon (Inpaint)",
    fontFamilyLabel: "Keluarga Font",
    sectionProvider: "PENYEDIA TERJEMAHAN AI",
    engineLabel: "Mesin Terjemahan Aktif",
    engineBta: "BTA Engine Ultra v2.5 (Direkomendasikan)",
    engineGemma: "Ollama Local - Gemma 3",
    engineLlava: "Ollama Local - LLaVA",
    adaptationLabel: "Mode Adaptasi Slang",
    adaptFaithful: "Setia pada Konteks Barat",
    adaptLiteral: "Literal",
    adaptNatural: "Natural Brasil",
    sectionSystem: "SISTEM DAN PINTASAN",
    shortcutLabel: "Pintasan Terjemahan Instan",
    exportConfig: "Ekspor Pengaturan",
    backupButton: "Buat Backup",
    ocrActive: "BTA Studio",
    helpButton: "Donate",
    statusUnchecked: "Server: belum dicek",
    checking: "Mengecek server lokal...",
    serverReady: "Server: siap di localhost:8000",
    serverMissing: "Server: jalankan run.bat dulu",
    sending: "Mengirim gambar yang terlihat...",
    translatingVisible: "Menerjemahkan gambar yang terlihat...",
    queued: (count) => `Sesi saat ini: ${count} gambar dikirim`,
    empty: "Tidak ada gambar besar yang terlihat",
    resetHint: "Muat ulang halaman untuk memulihkan gambar asli.",
    snipHint: "Potong manual akan dihubungkan ke content script.",
    paintHint: "Lukis manual akan dihubungkan ke content script.",
    backupHint: "Pengaturan disimpan ke Chrome Sync.",
    helpHint: "Bantuan: biarkan run.bat terbuka dan muat ulang ekstensi setelah perubahan.",
    autoLang: "Otomatis",
    indonesianLabel: "Bahasa Indonesia"
  }
};

const defaults = {
  sourceLang: "Japanese",
  targetLang: "Portuguese (Brazil)",
  autoTranslate: false,
  fastMode: true,
  uiLang: "pt",
  fontSize: 100,
  outlineSize: 4,
  balloonOpacity: 100,
  fontFamily: "Anime Ace"
};

const $ = (id) => document.getElementById(id);

function normalizeFontScale(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return defaults.fontSize;
  if (numeric <= 48) return Math.round((numeric / 22) * 100);
  return Math.max(50, Math.min(220, Math.round(numeric / 5) * 5));
}

function textFor(lang = $("uiLang")?.value) {
  return UI_TEXT[lang] || UI_TEXT.pt;
}

function normalizeLanguageValue(value) {
  const normalized = LANGUAGE_ALIASES[value] || value;
  return LANGUAGE_VALUES.has(normalized) ? normalized : "";
}

function capitalizeLabel(label, locale) {
  if (!label) return label;
  const first = label[0].toLocaleUpperCase(locale);
  return `${first}${label.slice(1)}`;
}

function languageLabel(lang, uiLang) {
  const text = textFor(uiLang);
  const locale = text.htmlLang || "en";
  if (lang.value === "Auto") return text.autoLang;
  if (lang.value === "Indonesian") return text.indonesianLabel;

  try {
    const display = new Intl.DisplayNames([locale], { type: "language" });
    return capitalizeLabel(display.of(lang.code) || lang.value, locale);
  } catch {
    return lang.value;
  }
}

function fillSelect(select, value, uiLang = $("uiLang")?.value || defaults.uiLang, fallback = defaults.sourceLang) {
  const normalizedValue = normalizeLanguageValue(value) || value;
  select.textContent = "";
  for (const lang of TRANSLATION_LANGUAGES) {
    const option = document.createElement("option");
    option.value = lang.value;
    option.textContent = languageLabel(lang, uiLang);
    select.append(option);
  }
  select.value = normalizeLanguageValue(normalizedValue) || fallback;
}

function setStatus(text, persist = false) {
  $("status").textContent = text;
  $("status").classList.add("show");
  if (!persist) {
    window.clearTimeout(setStatus.timer);
    setStatus.timer = window.setTimeout(() => $("status").classList.remove("show"), 2600);
  }
}

function applyUiLanguage(lang) {
  const text = textFor(lang);
  document.documentElement.lang = text.htmlLang;

  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.dataset.i18n;
    if (text[key]) node.textContent = text[key];
  });
  document.querySelectorAll("[data-i18n-title]").forEach((node) => {
    const key = node.dataset.i18nTitle;
    if (text[key]) node.title = text[key];
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    const key = node.dataset.i18nAriaLabel;
    if (text[key]) node.setAttribute("aria-label", text[key]);
  });
  $("uiLang").setAttribute("aria-label", text.uiLanguageTitle);

  const sourceValue = $("sourceLang").value || defaults.sourceLang;
  const targetValue = $("targetLang").value || defaults.targetLang;
  fillSelect($("sourceLang"), sourceValue, lang, defaults.sourceLang);
  fillSelect($("targetLang"), targetValue, lang, defaults.targetLang);
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function readSettingsFromUi() {
  return {
    sourceLang: $("sourceLang").value,
    targetLang: $("targetLang").value,
    autoTranslate: $("autoTranslate").checked,
    fastMode: $("fastMode").checked,
    uiLang: $("uiLang").value,
    fontSize: Number($("fontSize").value),
    outlineSize: Number($("outlineSize").value),
    balloonOpacity: Number($("balloonOpacity").value),
    fontFamily: $("fontFamily").value
  };
}

async function notifyPageSettings(settings, liveOnly = false) {
  const tab = await getActiveTab();
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type: "bta-settings", settings, liveOnly });
}

function persistSettingsSoon() {
  window.clearTimeout(persistSettingsSoon.timer);
  persistSettingsSoon.timer = window.setTimeout(() => {
    chrome.storage.sync.set(readSettingsFromUi());
  }, 300);
}

function notifyLiveSettingsSoon(settings) {
  window.clearTimeout(notifyLiveSettingsSoon.timer);
  notifyLiveSettingsSoon.timer = window.setTimeout(() => {
    notifyPageSettings(settings || readSettingsFromUi(), true);
  }, 180);
}

function previewStyleSettings() {
  const settings = readSettingsFromUi();
  persistSettingsSoon();
  notifyLiveSettingsSoon(settings);
  return settings;
}

async function saveSettings(options = {}) {
  if (!options || options instanceof Event || typeof options !== "object") options = {};
  const { notifyPage = true, persist = true, liveOnly = false } = options;
  const settings = readSettingsFromUi();
  if (persist) await chrome.storage.sync.set(settings);
  if (notifyPage) await notifyPageSettings(settings, liveOnly);
  return settings;
}

async function checkServer() {
  const text = textFor();
  setStatus(text.checking, true);
  try {
    const response = await fetch(`${SERVER}/api/models`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    setStatus(text.serverReady);
  } catch (error) {
    setStatus(text.serverMissing, true);
  }
}

async function translateVisibleImages() {
  const currentSettings = await saveSettings({ notifyPage: false });
  const tab = await getActiveTab();
  if (!tab?.id) return;

  const text = textFor();
  $("sessionInfo").textContent = text.translatingVisible;
  setStatus(text.sending, true);
  $("translateVisible").disabled = true;

  chrome.tabs.sendMessage(tab.id, {
    type: "bta-translate-current-visible",
    settings: { ...currentSettings, renderMode: "bubbles" }
  }, (response) => {
    $("translateVisible").disabled = false;
    const count = response?.count ?? 0;
    const error = response?.error;
    $("sessionInfo").textContent = count ? text.queued(count) : (error || text.empty);
    setStatus(count ? text.queued(count) : (error || text.empty));
  });
}

function switchTab(tabName) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${tabName}`);
  });
}

async function swapLanguages() {
  const source = $("sourceLang");
  const target = $("targetLang");
  if (source.value === "Auto") return;
  const previous = source.value;
  source.value = target.value;
  target.value = previous;
  await saveSettings();
}

function bindUi() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  $("sourceLang").addEventListener("change", saveSettings);
  $("targetLang").addEventListener("change", saveSettings);
  $("autoTranslate").addEventListener("change", saveSettings);
  $("fastMode").addEventListener("change", saveSettings);
  $("uiLang").addEventListener("change", async () => {
    applyUiLanguage($("uiLang").value);
    await saveSettings({ liveOnly: true });
  });
  $("fontSize").addEventListener("input", () => {
    $("fontSizeValue").textContent = `${$("fontSize").value}%`;
    previewStyleSettings();
  });
  $("fontSize").addEventListener("change", () => saveSettings({ liveOnly: true }));
  $("outlineSize").addEventListener("input", () => {
    $("outlineSizeValue").textContent = `${$("outlineSize").value}px`;
    previewStyleSettings();
  });
  $("outlineSize").addEventListener("change", () => saveSettings({ liveOnly: true }));
  $("balloonOpacity").addEventListener("input", () => {
    $("opacityValue").textContent = `${$("balloonOpacity").value}%`;
    previewStyleSettings();
  });
  $("balloonOpacity").addEventListener("change", () => saveSettings({ liveOnly: true }));
  $("fontFamily").addEventListener("change", () => saveSettings({ liveOnly: true }));
  $("swapLangs").addEventListener("click", swapLanguages);
  $("translateVisible").addEventListener("click", translateVisibleImages);
  $("resetPage").addEventListener("click", () => setStatus(textFor().resetHint));
  $("snipTool").addEventListener("click", () => setStatus(textFor().snipHint));
  $("paintTool").addEventListener("click", () => setStatus(textFor().paintHint));
  $("backupSettings").addEventListener("click", () => setStatus(textFor().backupHint));
}

document.addEventListener("DOMContentLoaded", async () => {
  const settings = { ...defaults, ...(await chrome.storage.sync.get(defaults)) };
  if (!UI_TEXT[settings.uiLang]) settings.uiLang = defaults.uiLang;
  settings.sourceLang = normalizeLanguageValue(settings.sourceLang) || defaults.sourceLang;
  settings.targetLang = normalizeLanguageValue(settings.targetLang) || defaults.targetLang;
  settings.fontSize = normalizeFontScale(settings.fontSize);
  if (settings.balloonOpacity === 90) settings.balloonOpacity = 100;
  if (!Number.isFinite(Number(settings.outlineSize))) settings.outlineSize = defaults.outlineSize;
  chrome.storage.sync.set({
    sourceLang: settings.sourceLang,
    targetLang: settings.targetLang,
    uiLang: settings.uiLang,
    fontSize: settings.fontSize,
    outlineSize: settings.outlineSize,
    balloonOpacity: settings.balloonOpacity
  });

  $("uiLang").value = settings.uiLang;
  fillSelect($("sourceLang"), settings.sourceLang, settings.uiLang, defaults.sourceLang);
  fillSelect($("targetLang"), settings.targetLang, settings.uiLang, defaults.targetLang);
  $("autoTranslate").checked = settings.autoTranslate;
  $("fastMode").checked = settings.fastMode;
  $("fontSize").value = settings.fontSize;
  $("fontSizeValue").textContent = `${settings.fontSize}%`;
  $("outlineSize").value = settings.outlineSize;
  $("outlineSizeValue").textContent = `${settings.outlineSize}px`;
  $("balloonOpacity").value = settings.balloonOpacity;
  $("opacityValue").textContent = `${settings.balloonOpacity}%`;
  if (settings.fontFamily) $("fontFamily").value = settings.fontFamily;
  applyUiLanguage(settings.uiLang);
  bindUi();
  checkServer();
});
