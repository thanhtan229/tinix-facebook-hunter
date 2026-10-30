/**
 * Tinix-Facebook-Hunter - Main WebUI Application Controller
 */

const state = {
  activeTab: "tab-downloader",
  wsConnected: false,
  scrapedPages: [],
  selectedPageNames: [],
  selectedPageUrls: [],
  spyPosts: [],
  selectedSpyPostIds: new Set(),
  downloadAccountIds: new Set(),
  downloadAccounts: [],
  accounts: [],
  selectedAccountId: null,
  selectedAccountIds: new Set(),
  selectedAccountsPreflightRunning: false,
  accountDetailData: null,
  accountSearchQuery: "",
  accountTabFilter: "all",
  accountStatusFilter: "all",
  accountSort: "name_asc",
  accountFavorites: new Set(JSON.parse(localStorage.getItem("tinix.account.favorites") || "[]")),
  accountListCollapsed: false,
  scrapeAccounts: [],
  favoritePages: [],
  favoriteGroups: [],
  favoriteGroupFilter: "all",
  favoritePageSearch: "",
  favoriteScanWasRunning: false,
  pageSearchResults: [],
  pageSearchWasRunning: false,
  pageSearchSort: { key: "relevance", direction: "desc" },
  favoriteSort: { key: "page_name", direction: "asc" },
  spySort: { key: "date", direction: "desc" },
  spyView: "grid",
  spyPostsRequest: 0,
  spyModalIndex: null,
  spyModalRequest: 0,
  spyModalDeleting: false,
  downloadRun: { total: 0, items: {}, accounts: {} },
  config: {}
};

const TAB2_PANEL_STORAGE_KEY = "tinix.tab2.collapsed-panels";
const FAVORITE_GROUP_FILTER_STORAGE_KEY = "tinix.tab2.favorite-group-filter";
const SCRAPE_AUTO_DOWNLOAD_KEY = "tinix.scrape-auto-download";
const APP_ACTIVITY_RESET_DELAY = 5000;
const SESSION_RECOVERY_STORAGE_KEY = "tinix.session-recovery-at";
const SESSION_RECOVERY_WINDOW_MS = 30000;
let appActivityResetTimer = null;

function resetAppActivity() {
  if (appActivityResetTimer) clearTimeout(appActivityResetTimer);
  appActivityResetTimer = null;
  const bar = document.getElementById("app-activity-bar");
  if (!bar) return;
  bar.className = "app-activity-bar is-idle";
  document.getElementById("app-activity-icon").textContent = "●";
  document.getElementById("app-activity-title").textContent = "Hệ thống sẵn sàng";
  document.getElementById("app-activity-message").textContent = "Theo dõi tiến trình và lỗi của toàn bộ tác vụ tại đây.";
  document.getElementById("app-activity-percent").hidden = true;
  document.getElementById("app-activity-progress-value").style.width = "0%";
}

function setAppActivity({ type = "info", title = "Thông báo", message = "", current, total, autoReset = false }) {
  if (appActivityResetTimer) clearTimeout(appActivityResetTimer);
  appActivityResetTimer = null;

  const bar = document.getElementById("app-activity-bar");
  if (!bar) return;
  const normalizedType = ["running", "success", "warning", "error"].includes(type) ? type : "idle";
  const hasProgress = Number.isFinite(Number(current)) && Number(total) > 0;
  const progressPercent = hasProgress
    ? Math.max(0, Math.min(100, Math.round((Number(current) / Number(total)) * 100)))
    : 0;

  bar.className = `app-activity-bar is-${normalizedType}${type === "running" && !hasProgress ? " is-indeterminate" : ""}`;
  document.getElementById("app-activity-icon").textContent = {
    running: "●", success: "✓", warning: "!", error: "×", idle: "●"
  }[normalizedType];
  document.getElementById("app-activity-title").textContent = title;
  document.getElementById("app-activity-message").textContent = message;

  const percent = document.getElementById("app-activity-percent");
  percent.hidden = !hasProgress;
  if (hasProgress) percent.textContent = `${progressPercent}%`;
  document.getElementById("app-activity-progress-value").style.width = hasProgress ? `${progressPercent}%` : "0%";

  if (autoReset) {
    appActivityResetTimer = setTimeout(resetAppActivity, typeof autoReset === "number" ? autoReset : APP_ACTIVITY_RESET_DELAY);
  }
}

function setAppActivityFromProgress(data) {
  const taskLabels = {
    download: "Tải media",
    scraper: "Quét Fanpage",
    page_search: "Tìm Fanpage"
  };
  const label = taskLabels[data.task];
  if (!label) return;

  const status = String(data.status || "").toLowerCase();
  const total = Number(data.total) || 0;
  const current = Number(data.current) || 0;
  const details = String(data.speed || "").trim() || (total ? `${current}/${total}` : "Đang xử lý tác vụ");

  if (status === "failed") {
    setAppActivity({ type: "error", title: `${label} thất bại`, message: details, current, total });
  } else if (status === "stopped") {
    setAppActivity({ type: "warning", title: `${label} đã dừng`, message: details, current, total, autoReset: 8000 });
  } else if (status === "partial") {
    setAppActivity({ type: "warning", title: `${label} hoàn tất một phần`, message: details, current, total, autoReset: 8000 });
  } else if (status === "completed") {
    setAppActivity({ type: "success", title: `${label} hoàn tất`, message: details, current: total || current, total: total || current, autoReset: true });
  } else {
    setAppActivity({ type: "running", title: `Đang ${label.toLocaleLowerCase("vi")}`, message: details, current, total });
  }
}

function initGlobalApiNotifications() {
  if (window.__tinixApiNotificationsInstalled) return;
  window.__tinixApiNotificationsInstalled = true;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    try {
      const response = await nativeFetch(...args);
      if (!response.ok) {
        if (response.status === 401) scheduleSessionRecovery();
        setAppActivity({
          type: "error",
          title: `Yêu cầu thất bại (${response.status})`,
          message: "Máy chủ không thể xử lý yêu cầu. Hãy xem thông báo chi tiết hoặc thử lại."
        });
      }
      return response;
    } catch (error) {
      if (error?.name !== "AbortError") {
        setAppActivity({
          type: "error",
          title: "Lỗi kết nối",
          message: "Không thể kết nối tới ứng dụng. Hãy kiểm tra lại trạng thái máy chủ."
        });
      }
      throw error;
    }
  };
}

function scheduleSessionRecovery() {
  const now = Date.now();
  const lastRecovery = Number(sessionStorage.getItem(SESSION_RECOVERY_STORAGE_KEY) || 0);
  if (now - lastRecovery < SESSION_RECOVERY_WINDOW_MS) return;
  sessionStorage.setItem(SESSION_RECOVERY_STORAGE_KEY, String(now));
  setAppActivity({
    type: "warning",
    title: "Ứng dụng vừa khởi động lại",
    message: "Đang tải lại trang để tạo phiên kết nối mới."
  });
  window.setTimeout(() => window.location.reload(), 250);
}

function normalizePageInputLines(value) {
  return [...new Set(String(value || "").split(/\r?\n/).map(item => item.trim()).filter(Boolean).map(item => {
    if (/^https?:\/\//i.test(item)) return item;
    if (/^(?:www\.)?facebook\.com\//i.test(item)) return `https://${item}`;
    return `https://www.facebook.com/${item.replace(/^\/+|\/+$/g, "")}`;
  }))];
}

function getSharedScrapeSettings() {
  const accountChoice = document.getElementById("scrape-common-account")?.value || "auto";
  return {
    accountChoice,
    accountMode: ["auto", "default"].includes(accountChoice) ? accountChoice : "specific",
    accountId: ["auto", "default"].includes(accountChoice) ? null : (parseInt(accountChoice) || null),
    maxConcurrency: Math.max(1, Math.min(parseInt(document.getElementById("scrape-common-concurrency")?.value) || 2, 8)),
    delayMode: document.getElementById("scrape-common-delay")?.value || "balanced",
    scanLimit: Math.max(5, Math.min(parseInt(document.getElementById("scrape-common-limit")?.value) || 100, 2000)),
    autoDownload: Boolean(document.getElementById("scrape-auto-download")?.checked)
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function encodeInlineArg(value) {
  return encodeURIComponent(String(value ?? "")).replace(/'/g, "%27");
}

function readCollapsedPanelState() {
  try {
    const value = JSON.parse(localStorage.getItem(TAB2_PANEL_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch (_) {
    return {};
  }
}

function setCollapsiblePanel(panelKey, collapsed, persist = true) {
  const card = document.querySelector(`.collapsible-card[data-panel-key="${panelKey}"]`);
  if (!card) return;
  const body = card.querySelector(".collapsible-card-body");
  const button = card.querySelector(".panel-collapse-toggle");
  if (!body || !button) return;

  const isCollapsed = Boolean(collapsed);
  card.classList.toggle("is-collapsed", isCollapsed);
  body.hidden = isCollapsed;
  button.setAttribute("aria-expanded", String(!isCollapsed));
  const label = button.querySelector(".panel-collapse-label");
  const chevron = button.querySelector(".panel-collapse-chevron");
  if (label) label.textContent = isCollapsed ? "Mở rộng" : "Thu gọn";
  if (chevron) chevron.textContent = isCollapsed ? "▾" : "▴";

  if (persist) {
    const saved = readCollapsedPanelState();
    saved[panelKey] = isCollapsed;
    try { localStorage.setItem(TAB2_PANEL_STORAGE_KEY, JSON.stringify(saved)); } catch (_) {}
  }
}

function initCollapsiblePanels() {
  const saved = readCollapsedPanelState();
  document.querySelectorAll(".collapsible-card[data-panel-key]").forEach(card => {
    const panelKey = card.dataset.panelKey;
    setCollapsiblePanel(panelKey, saved[panelKey] === true, false);
    const button = card.querySelector(".panel-collapse-toggle");
    const header = card.querySelector(".collapsible-card-header");
    if (button) {
      button.addEventListener("click", event => {
        event.stopPropagation();
        setCollapsiblePanel(panelKey, !card.classList.contains("is-collapsed"));
      });
    }
    if (header) {
      header.addEventListener("click", event => {
        if (event.target.closest("button, a, input, select, textarea, label")) return;
        setCollapsiblePanel(panelKey, !card.classList.contains("is-collapsed"));
      });
    }
  });
}

function updateSortIndicators(group, sort) {
  document.querySelectorAll(`[data-sort-indicator^="${group}:"]`).forEach(indicator => {
    const key = indicator.getAttribute("data-sort-indicator").split(":")[1];
    indicator.textContent = sort.key === key ? (sort.direction === "asc" ? "▲" : "▼") : "↕";
  });
}

function cycleTableSort(current, key, numericKeys, fallback) {
  const firstDirection = numericKeys.includes(key) ? "desc" : "asc";
  if (current.key !== key) return { key, direction: firstDirection };
  if (current.direction === firstDirection) {
    return { key, direction: firstDirection === "desc" ? "asc" : "desc" };
  }
  return { ...fallback };
}

function compareTableValues(left, right, direction, numeric = false) {
  const factor = direction === "asc" ? 1 : -1;
  if (numeric) return ((Number(left) || 0) - (Number(right) || 0)) * factor;
  return String(left || "").localeCompare(String(right || ""), "vi", { numeric: true, sensitivity: "base" }) * factor;
}


// ─── WebSocket Connection ───────────────────────────────────────────────────

let _wsRetryDelay = 3000;

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  const ws = new WebSocket(wsUrl);

  const badge = document.getElementById("ws-badge");

  ws.onopen = () => {
    state.wsConnected = true;
    _wsRetryDelay = 3000;
    if (badge) {
      badge.className = "badge badge-green";
      badge.textContent = "🟢 Realtime Connected";
    }
    appendLog("Hệ thống kết nối thời gian thực thành công!", "OK");
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "log") {
        appendLog(data.message, data.level || "INFO");
        const level = String(data.level || "INFO").toUpperCase();
        if (level === "ERROR" || level === "CRITICAL") {
          setAppActivity({ type: "error", title: "Lỗi tác vụ nền", message: String(data.message || "Đã xảy ra lỗi không xác định.") });
        } else if (level === "WARNING") {
          setAppActivity({ type: "warning", title: "Tác vụ cần lưu ý", message: String(data.message || "Hãy kiểm tra nhật ký tác vụ.") });
        }
      } else if (data.type === "progress") {
        setAppActivityFromProgress(data);
        handleProgressUpdate(data);
      } else if (data.type === "download_account") {
        handleDownloadAccountStatus(data);
      } else if (data.type === "download_item") {
        handleDownloadItemStatus(data);
      }
    } catch (e) {
      console.error("WS Parse Error", e);
    }
  };

  ws.onclose = () => {
    state.wsConnected = false;
    if (badge) {
      badge.className = "badge badge-amber";
      badge.textContent = "🟡 Đang kết nối lại...";
    }
    setTimeout(initWebSocket, _wsRetryDelay);
    _wsRetryDelay = Math.min(_wsRetryDelay * 1.5, 30000);
  };

  ws.onerror = () => {
    if (badge) {
      badge.className = "badge badge-red";
      badge.textContent = "🔴 Mất kết nối WS";
    }
  };
}

function appendLog(message, level = "INFO") {
  const container = document.getElementById("terminal-logs");
  const row = document.createElement("div");
  row.className = "log-row";

  const timeStr = new Date().toLocaleTimeString("vi-VN", { hour12: false });
  const tag = document.createElement("span");
  tag.className = `log-tag ${String(level).replace(/[^A-Z]/g, "")}`;
  tag.textContent = `[${level}]`;
  const time = document.createElement("span");
  time.style.color = "#64748B";
  time.textContent = `[${timeStr}]`;
  const text = document.createElement("span");
  text.textContent = String(message ?? "");
  row.append(tag, time, text);

  container.appendChild(row);

  if (document.getElementById("terminal-autoscroll").checked) {
    container.scrollTop = container.scrollHeight;
  }
}

function handleProgressUpdate(data) {
  if (data.task === "download") {
    if (data.total > 0) state.downloadRun.total = Number(data.total);
    const text = document.getElementById("dl-progress-text");
    const percent = document.getElementById("dl-progress-percent");
    const bar = document.getElementById("dl-progress-bar");

    const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
    text.textContent = `Tải media: ${data.current}/${data.total} (${data.speed || ''})`;
    percent.textContent = `${pct}%`;
    bar.style.width = `${pct}%`;

    if (data.status === "completed") {
      fetchStats();
      if (state.activeTab === "tab-spy") loadSpyPosts();
      showToast("Tải xuống hoàn tất!", "success");
    } else if (data.status === "partial") {
      fetchStats();
      if (state.activeTab === "tab-spy") loadSpyPosts();
      showToast("Đã tải một phần; có bài bị lỗi. Hãy kiểm tra log.", "warning");
    } else if (data.status === "failed") {
      text.textContent = `Tải thất bại: ${data.speed || `${data.current}/${data.total}`}`;
      fetchStats();
      if (state.activeTab === "tab-spy") loadSpyPosts();
      showToast("Tải thất bại. Hãy kiểm tra log chi tiết.", "error");
    }
  }
}

function resetDownloadStatus(total = 0) {
  state.downloadRun = { total: Number(total) || 0, items: {}, accounts: {} };
  renderDownloadStatus();
}

function handleDownloadAccountStatus(data) {
  const accountId = Number(data.account_id) || 0;
  if (!accountId) return;
  state.downloadRun.accounts[accountId] = {
    account_id: accountId,
    label: data.label || `Account #${accountId}`,
    state: data.state || "checking",
    code: data.code || "",
    message: data.message || "",
    processed_posts: Number(data.processed_posts) || 0,
    consecutive_errors: Number(data.consecutive_errors) || 0,
    rate_limit_count: Number(data.rate_limit_count) || 0,
    cooldown_seconds: Number(data.cooldown_seconds) || 0
  };
  renderDownloadStatus();
}

function handleDownloadItemStatus(data) {
  const index = Number(data.index) || 0;
  if (!index) return;
  state.downloadRun.items[index] = {
    state: data.state || "",
    message: data.message || "",
    code: data.code || ""
  };
  renderDownloadStatus();
}

function renderDownloadStatus() {
  const run = state.downloadRun;
  const items = Object.values(run.items || {});
  const success = items.filter(item => item.state === "success").length;
  const failed = items.filter(item => item.state === "failed").length;
  const retrying = items.filter(item => item.state === "retrying").length;
  const queued = Math.max(0, (Number(run.total) || 0) - success - failed - retrying);
  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  };
  setText("dl-count-queued", run.total ? queued : "—");
  setText("dl-count-success", success);
  setText("dl-count-retrying", retrying);
  setText("dl-count-failed", failed);

  const list = document.getElementById("dl-account-status-list");
  if (!list) return;
  const accounts = Object.values(run.accounts || {});
  if (!accounts.length) {
    list.innerHTML = '<span class="text-muted">Chưa có tác vụ tải đang chạy.</span>';
    return;
  }
  list.innerHTML = accounts.map(account => {
    const stateName = String(account.state || "checking").replace(/[^a-z]/gi, "").toLowerCase() || "checking";
    const label = escapeHtml(account.label || `Account #${account.account_id}`);
    const pacing = [];
    if (account.processed_posts) pacing.push(`${account.processed_posts} bài`);
    if (account.rate_limit_count) pacing.push(`${account.rate_limit_count} lần giới hạn`);
    if (account.cooldown_seconds) pacing.push(`còn ${account.cooldown_seconds}s`);
    const detail = escapeHtml(`${account.message || account.code || "Đang chờ"}${pacing.length ? ` · ${pacing.join(", ")}` : ""}`);
    return `<span class="download-worker-chip ${stateName}" title="${detail}">#${Number(account.account_id)} · ${label}: ${detail}</span>`;
  }).join("");
}

async function refreshPendingAutoDownloads() {
  const queueStatus = document.getElementById("dl-auto-queue-status");
  const clearButton = document.getElementById("btn-clear-dl-queue");
  const pauseButton = document.getElementById("btn-pause-dl");
  if (!queueStatus) return;
  try {
    const response = await fetch("/api/download/status");
    const json = await response.json();
    const download = json?.data || {};
    const pending = json?.data?.pending_auto_downloads || {};
    const batches = Number(pending.batches) || 0;
    const items = Number(pending.items) || 0;
    const runningBatches = Number(pending.running_batches) || 0;
    if (pauseButton) {
      const isRunning = Boolean(download.is_running);
      pauseButton.disabled = !isRunning;
      pauseButton.textContent = download.is_paused ? "▶ Tiếp tục" : "⏸ Tạm dừng";
    }
    queueStatus.textContent = batches
      ? `Auto Download đang chờ: ${items} bài trong ${batches} batch.`
      : (runningBatches ? "Auto Download đang khởi động batch đã lưu." : "");
    if (clearButton) clearButton.style.display = batches ? "" : "none";
  } catch (_error) {
    queueStatus.textContent = "";
    if (clearButton) clearButton.style.display = "none";
  }
}

// ─── Tab Switching ──────────────────────────────────────────────────────────

function initTabs() {
  const navItems = document.querySelectorAll(".nav-item");
  const panels = document.querySelectorAll(".tab-panel");
  const title = document.getElementById("current-tab-title");

  const tabTitles = {
    "tab-downloader": "📥 Tải Facebook — Media Downloader",
    "tab-scraper": "🔍 Quét Page — Facebook Page Scraper",
    "tab-spy": "📊 Kho Bài Viết — Spy Studio",
    "tab-accounts": "👥 Quản Lý Tài Khoản & Chrome Profiles"
  };

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const target = item.getAttribute("data-tab");
      navItems.forEach(n => n.classList.remove("active"));
      panels.forEach(p => p.classList.remove("active"));

      item.classList.add("active");
      document.getElementById(target).classList.add("active");
      title.textContent = tabTitles[target] || "Tinix-Facebook-Hunter";
      state.activeTab = target;

      if (target === "tab-spy") loadSpyPages();
      if (target === "tab-scraper") {
        loadScrapeAccounts();
        loadFavoritePages();
      }
      if (target === "tab-accounts") loadAccounts();
    });
  });
}

// ─── API Helpers ────────────────────────────────────────────────────────────

async function fetchStats() {
  try {
    const res = await fetch("/api/system/stats");
    const json = await res.json();
    if (json.status === "success") {
      document.getElementById("stat-total-posts").textContent = json.data.total_posts;
      document.getElementById("stat-scraped-posts").textContent = json.data.scraped_posts;
      document.getElementById("stat-direct-posts").textContent = json.data.direct_posts;
      document.getElementById("stat-downloaded-posts").textContent = json.data.downloaded_posts;
      document.getElementById("stat-total-pages").textContent = json.data.total_pages;
      document.getElementById("stat-active-accounts").textContent = json.data.active_accounts;
    }
  } catch (e) {}
}

async function loadConfig() {
  try {
    const res = await fetch("/api/system/config");
    const json = await res.json();
    if (json.status === "success") {
      state.config = json.data;
      syncOutputDirectoryInputs();
      const threads = document.getElementById("dl-threads");
      if (threads) {
        const configuredThreads = String(Number(json.data.max_threads) || 3);
        threads.value = [...threads.options].some(option => option.value === configuredThreads)
          ? configuredThreads
          : "3";
      }
      const useAccounts = document.getElementById("dl-use-accounts");
      if (useAccounts) useAccounts.checked = json.data.download_use_accounts !== false;
    }
  } catch (e) {}
}

async function loadAppVersion() {
  const badge = document.getElementById("app-version-badge");
  try {
    const res = await fetch("/api/system/health");
    const json = await res.json();
    const version = json?.data?.version;
    if (badge && res.ok && version) {
      badge.textContent = `v${version}`;
      badge.title = `Tinix-Facebook-Hunter phiên bản ${version}`;
    }
    renderSystemReadiness(json?.data, res.ok);
  } catch (_) {
    if (badge) badge.textContent = "Version";
    renderSystemReadiness(null, false);
  }
}

function renderSystemReadiness(data, requestOk) {
  const panel = document.getElementById("system-readiness");
  const title = document.getElementById("system-readiness-title");
  const message = document.getElementById("system-readiness-message");
  if (!panel || !title || !message) return;
  const labels = {
    database: "database", schema: "schema", windows: "Windows",
    chrome: "Google Chrome", playwright: "Playwright", yt_dlp: "yt-dlp"
  };
  const missing = Object.entries(data?.checks || {})
    .filter(([, ready]) => !ready)
    .map(([key]) => labels[key] || key);
  if (requestOk && data?.ready) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  title.textContent = "Cần hoàn tất thiết lập trước khi chạy tác vụ";
  message.textContent = missing.length
    ? `Chưa sẵn sàng: ${missing.join(", ")}. Cài đặt hoặc khôi phục các thành phần này rồi tải lại trang.`
    : "Không thể kiểm tra tình trạng hệ thống. Hãy kiểm tra máy chủ local rồi tải lại trang.";
  setAppActivity({ type: "warning", title: "Môi trường chưa sẵn sàng", message: message.textContent });
}

function openAccountsWorkspace() {
  document.querySelector('.nav-item[data-tab="tab-accounts"]')?.click();
}

function updateScrapeExecutionSummary() {
  const summary = document.getElementById("scrape-execution-summary");
  if (!summary) return;
  const settings = getSharedScrapeSettings();
  summary.textContent = `Mỗi lần quét: tối đa ${settings.scanLimit} bài/Page · ${settings.maxConcurrency} luồng · ${settings.autoDownload ? "tự tải media bài mới" : "chỉ lưu dữ liệu vào Kho Bài Viết"}.`;
}

function initScrapeExecutionSettings() {
  const toggle = document.getElementById("scrape-auto-download");
  if (toggle) {
    try { toggle.checked = localStorage.getItem(SCRAPE_AUTO_DOWNLOAD_KEY) !== "false"; } catch (_) {}
    toggle.addEventListener("change", () => {
      try { localStorage.setItem(SCRAPE_AUTO_DOWNLOAD_KEY, String(toggle.checked)); } catch (_) {}
      updateScrapeExecutionSummary();
    });
  }
  ["scrape-common-concurrency", "scrape-common-limit"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", updateScrapeExecutionSummary);
  });
  updateScrapeExecutionSummary();
}

function taskRunTypeLabel(type) {
  return { download: "Tải media", scrape_quick: "Quét Fanpage", scrape_favorites: "Quét yêu thích", page_search: "Tìm Fanpage" }[type] || "Tác vụ";
}

function taskRunStatusLabel(status) {
  return {
    running: "Đang chạy", completed: "Hoàn tất", partial: "Hoàn tất một phần",
    failed: "Thất bại", stopped: "Đã dừng", interrupted: "Bị gián đoạn"
  }[status] || status;
}

function taskRunSummary(run) {
  const summary = run.summary || {};
  const parts = [`${Number(run.completed_items) || 0}/${Number(run.total_items) || 0} mục`];
  if (summary.scan_limit) parts.push(`${summary.scan_limit} bài/Page`);
  if (Object.hasOwn(summary, "download_media")) parts.push(summary.download_media ? "có tải media" : "chỉ lưu dữ liệu");
  if (run.error_message) parts.push(run.error_message);
  return parts.join(" · ");
}

async function loadRecentTaskRuns() {
  const container = document.getElementById("recent-task-runs-list");
  if (!container) return;
  try {
    const res = await fetch("/api/system/task-runs");
    const json = await res.json();
    const runs = res.ok ? (json.data || []) : [];
    container.innerHTML = runs.length ? runs.map(run => `
      <div class="task-run-row">
        <strong>${escapeHtml(taskRunTypeLabel(run.task_type))}</strong>
        <span class="task-run-status ${escapeHtml(run.status || "")}">${escapeHtml(taskRunStatusLabel(run.status))}</span>
        <small title="${escapeHtml(run.error_message || "")}">${escapeHtml(taskRunSummary(run))}<br>${escapeHtml(run.finished_at || run.started_at || "")}</small>
      </div>`).join("") : '<span class="text-muted">Chưa có tác vụ nào được lưu.</span>';
  } catch (_) {
    container.innerHTML = '<span class="text-muted">Không thể tải lịch sử tác vụ.</span>';
  }
}

function syncOutputDirectoryInputs() {
  const sidebarInput = document.getElementById("sidebar-output-dir");
  const settingsInput = document.getElementById("setting-output-dir");
  const outputDir = state.config.output_dir || ".";
  if (sidebarInput) sidebarInput.value = outputDir;
  if (settingsInput) settingsInput.value = outputDir;
}

async function saveOutputDirectory(outputDir, { quiet = false } = {}) {
  const path = String(outputDir || "").trim();
  if (!path) {
    showToast("Vui lòng nhập đường dẫn thư mục tải về.", "warning");
    return false;
  }
  try {
    const res = await fetch("/api/system/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_dir: path })
    });
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể lưu thư mục tải về.", "error");
      return false;
    }
    state.config = { ...state.config, ...json.data };
    syncOutputDirectoryInputs();
    if (!quiet) showToast("Đã lưu thư mục tải về.", "success");
    return true;
  } catch (e) {
    showToast("Lỗi kết nối khi lưu thư mục tải về.", "error");
    return false;
  }
}

// ─── Tab 1: Downloader ──────────────────────────────────────────────────────

async function refreshDownloadAccountOptions() {
  const container = document.getElementById("dl-account-ids");
  if (!container) return [];
  try {
    const response = await fetch("/api/accounts/");
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể tải danh sách account");
    const accounts = (result.data || []).filter(account => account.is_active);
    state.downloadAccounts = accounts;
    const activeIds = new Set(accounts.map(account => Number(account.id)));
    state.downloadAccountIds = new Set([...state.downloadAccountIds].filter(id => activeIds.has(Number(id))));
    renderDownloadAccountOptions();
    return accounts;
  } catch (_) {
    container.innerHTML = "";
    return [];
  }
}

function selectedDownloadAccountIds() {
  return [...state.downloadAccountIds].map(Number).filter(Boolean);
}

function renderDownloadAccountOptions() {
  const container = document.getElementById("dl-account-ids");
  const summary = document.getElementById("dl-account-picker-summary");
  if (!container || !summary) return;
  const selectedCount = state.downloadAccountIds.size;
  summary.textContent = selectedCount
    ? `${selectedCount} Account đã chọn`
    : "Tự chọn Account khả dụng";
  const disabled = !document.getElementById("dl-use-accounts")?.checked;
  container.innerHTML = `
    <div style="display:flex; gap:6px; margin-bottom:8px;">
      <button type="button" class="btn btn-secondary btn-sm" id="btn-dl-account-select-all" ${disabled ? "disabled" : ""}>Chọn tất cả</button>
      <button type="button" class="btn btn-secondary btn-sm" id="btn-dl-account-clear" ${disabled ? "disabled" : ""}>Tự chọn</button>
    </div>
    ${state.downloadAccounts.map(account => {
      const id = Number(account.id);
      const name = escapeHtml(account.label || account.username || `Account #${id}`);
      const ready = account.preflight_status === "READY" ? " · sẵn sàng" : "";
      return `<label style="display:block; padding:4px 0; cursor:${disabled ? "default" : "pointer"};"><input class="dl-account-option" type="checkbox" value="${id}" ${state.downloadAccountIds.has(id) ? "checked" : ""} ${disabled ? "disabled" : ""}> ${name}${ready}</label>`;
    }).join("") || '<span class="text-muted">Chưa có Account active.</span>'}`;
  container.querySelectorAll(".dl-account-option").forEach(input => {
    input.addEventListener("change", event => {
      const id = Number(event.target.value);
      if (event.target.checked) state.downloadAccountIds.add(id);
      else state.downloadAccountIds.delete(id);
      renderDownloadAccountOptions();
    });
  });
  document.getElementById("btn-dl-account-select-all")?.addEventListener("click", () => {
    state.downloadAccountIds = new Set(state.downloadAccounts.map(account => Number(account.id)));
    renderDownloadAccountOptions();
  });
  document.getElementById("btn-dl-account-clear")?.addEventListener("click", () => {
    state.downloadAccountIds.clear();
    renderDownloadAccountOptions();
  });
}

function initDownloader() {
  refreshDownloadAccountOptions();
  document.getElementById("dl-use-accounts").addEventListener("change", event => {
    renderDownloadAccountOptions();
  });
  document.getElementById("btn-start-dl").addEventListener("click", async () => {
    const urls = document.getElementById("dl-urls").value.trim();
    if (!urls) {
      showToast("Vui lòng nhập ít nhất 1 link Facebook!", "warning");
      return;
    }

    const threads = parseInt(document.getElementById("dl-threads").value);
    const useAccounts = document.getElementById("dl-use-accounts").checked;
    const accountIds = selectedDownloadAccountIds();
    if (useAccounts) {
      try {
        const activeAccounts = await refreshDownloadAccountOptions();
        if (!activeAccounts.length) {
          setAppActivity({
            type: "warning",
            title: "Chưa có account sẵn sàng",
            message: "Tạo account, mở Chrome để đăng nhập Facebook và chạy Check Preflight trước khi tải bằng Profile."
          });
          showToast("Chưa có account active. Đang mở tab Tài Khoản để thiết lập.", "warning");
          openAccountsWorkspace();
          return;
        }
      } catch (_) {
        showToast("Không thể kiểm tra account trước khi tải.", "error");
        return;
      }
    }
    if (threads > 3) {
      showToast("Từ 4 worker trở lên sẽ tăng nguy cơ Facebook yêu cầu xác nhận lại.", "warning");
    }
    resetDownloadStatus(urls.split(/\r?\n/).filter(Boolean).length);
    setAppActivity({ type: "running", title: "Chuẩn bị tải media", message: "Đang gửi yêu cầu khởi động tác vụ..." });

    try {
      const res = await fetch("/api/download/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls, max_threads: threads, use_accounts: useAccounts, account_ids: accountIds })
      });
      const json = await res.json();
      if (res.ok) {
        showToast("Đã bắt đầu tiến trình tải xuống!", "success");
      } else {
        showToast(json.detail || "Lỗi khi bắt đầu", "error");
      }
    } catch (e) {
      showToast("Không thể gọi API tải", "error");
    }
  });

  document.getElementById("btn-pause-dl").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    try {
      const statusResponse = await fetch("/api/download/status");
      const status = await statusResponse.json();
      const download = status?.data || {};
      if (!statusResponse.ok || !download.is_running) {
        showToast("Không có tác vụ tải nào đang chạy", "info");
        refreshPendingAutoDownloads();
        return;
      }
      const isPaused = Boolean(download.is_paused);
      const response = await fetch(isPaused ? "/api/download/resume" : "/api/download/pause", { method: "POST" });
      const result = await response.json();
      if (!response.ok) {
        showToast(result.detail || "Không thể cập nhật trạng thái tải", "error");
        return;
      }
      button.textContent = isPaused ? "⏸ Tạm dừng" : "▶ Tiếp tục";
      showToast(result.message || (isPaused ? "Đã tiếp tục" : "Đã tạm dừng"), "info");
    } catch (error) {
      showToast("Không thể cập nhật trạng thái tải", "error");
    }
  });

  document.getElementById("btn-stop-dl").addEventListener("click", async () => {
    const response = await fetch("/api/download/stop", { method: "POST" });
    const result = await response.json();
    showToast(result.message || "Đã dừng lượt tải hiện tại", response.ok ? "info" : "error");
  });

  document.getElementById("btn-stop-all-dl").addEventListener("click", async () => {
    const response = await fetch("/api/download/stop-all", { method: "POST" });
    const result = await response.json();
    showToast(
      response.ok ? `Đã dừng tất cả và hủy ${Number(result.cancelled_batches) || 0} batch chờ` : (result.detail || "Không thể dừng tất cả"),
      response.ok ? "warning" : "error"
    );
    refreshPendingAutoDownloads();
  });

  document.getElementById("btn-clear-dl-queue").addEventListener("click", async () => {
    const response = await fetch("/api/download/queue/clear", { method: "POST" });
    const result = await response.json();
    showToast(
      response.ok ? `Đã hủy ${Number(result.cancelled_batches) || 0} batch chờ` : (result.detail || "Không thể hủy queue"),
      response.ok ? "info" : "error"
    );
    refreshPendingAutoDownloads();
  });

  document.getElementById("dl-threads").addEventListener("change", (event) => {
    if (Number(event.target.value) > 3) {
      showToast("Khuyến nghị giữ tối đa 3 account worker cho tác vụ thường ngày.", "warning");
    }
  });
}

// ─── Tab 2: Scraper ─────────────────────────────────────────────────────────

function initScraper() {
  document.getElementById("btn-start-scrape").addEventListener("click", async () => {
    const pageUrls = normalizePageInputLines(document.getElementById("scrape-url").value);
    if (!pageUrls.length) {
      showToast("Vui lòng nhập ít nhất một URL Fanpage!", "warning");
      return;
    }

    const mode = "All";
    const settings = getSharedScrapeSettings();
    setAppActivity({ type: "running", title: "Chuẩn bị quét Fanpage", message: `Đang xếp hàng ${pageUrls.length} Fanpage...` });

    try {
      const res = await fetch("/api/scrape/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_urls: pageUrls, mode, limit: settings.scanLimit,
          account_mode: settings.accountMode, account_id: settings.accountId,
          max_concurrency: settings.maxConcurrency,
          download_media: settings.autoDownload, delay_mode: settings.delayMode
        })
      });
      const json = await res.json();
      if (res.ok) {
        state.favoriteScanWasRunning = true;
        setFavoriteScanControls(true);
        showToast(`Đã xếp hàng ${pageUrls.length} Fanpage · ${json.workers || 1} luồng`, "success");
      } else {
        showToast(json.detail || "Lỗi bắt đầu quét", "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", "error");
    }
  });

  document.getElementById("btn-stop-scrape").addEventListener("click", async () => {
    await fetch("/api/scrape/stop", { method: "POST" });
    showToast("Đã gửi lệnh dừng quét", "info");
  });

  document.getElementById("btn-save-favorite").addEventListener("click", saveFavoriteFromForm);
  document.getElementById("btn-scan-selected-favorites")?.addEventListener("click", () => {
    const ids = selectedVisibleFavoriteIds();
    if (!ids.length) return showToast("Vui lòng chọn ít nhất một Fanpage để quét", "warning");
    scanFavoritePages(ids);
  });
  document.getElementById("btn-scan-older-favorites")?.addEventListener("click", () => {
    const ids = selectedVisibleFavoriteIds();
    if (!ids.length) return showToast("Vui lòng chọn ít nhất một Fanpage để quét", "warning");
    scanFavoritePages(ids, "older");
  });
  document.getElementById("btn-reset-selected-favorites")?.addEventListener("click", bulkResetFavoritePagesUi);
  document.getElementById("btn-delete-selected-favorites")?.addEventListener("click", bulkDeleteFavoritePagesUi);
  document.getElementById("favorite-group-trigger")?.addEventListener("click", toggleFavoriteGroupMenu);
  document.getElementById("btn-remove-selected-from-group")?.addEventListener("click", removeSelectedFromCurrentGroup);
  document.getElementById("btn-stop-all-favorites").addEventListener("click", stopAllFavoriteScans);
  document.getElementById("favorite-select-all").addEventListener("change", event => {
    getVisibleFavoritePages().forEach(page => { page._selected = event.target.checked; });
    renderFavoritePages();
  });
  document.getElementById("favorite-page-search").addEventListener("input", event => {
    state.favoritePageSearch = event.target.value.trim().toLocaleLowerCase("vi");
    renderFavoritePages();
  });
  document.getElementById("btn-create-favorite-group")?.addEventListener("click", createFavoriteGroupUi);

  document.addEventListener("click", event => {
    const wrap = document.getElementById("favorite-group-dropdown-wrap");
    if (wrap && !wrap.contains(event.target)) {
      closeFavoriteGroupMenu();
    }
  });
  document.getElementById("btn-start-page-search").addEventListener("click", startPageSearch);
  document.getElementById("btn-stop-page-search").addEventListener("click", async () => {
    await fetch("/api/scrape/stop", { method: "POST" });
    showToast("Đã gửi lệnh dừng tìm kiếm", "info");
  });
  document.getElementById("page-search-keyword").addEventListener("keydown", event => {
    if (event.key === "Enter") startPageSearch();
  });
  document.getElementById("page-search-select-all").addEventListener("change", event => {
    state.pageSearchResults.forEach(page => {
      if (!page.is_favorite) page._selected = event.target.checked;
    });
    renderPageSearchResults();
  });
  document.getElementById("btn-save-selected-search").addEventListener("click", saveSelectedSearchPages);
}

async function loadScrapeAccounts() {
  try {
    const res = await fetch("/api/accounts/");
    const json = await res.json();
    state.scrapeAccounts = res.ok ? (json.data || []).filter(account => account.is_active) : [];
    const select = document.getElementById("scrape-common-account");
    const current = select.value || "auto";
    select.innerHTML = `
      <option value="auto">Tự chọn Account khả dụng</option>
      <option value="default">Profile mặc định</option>` + state.scrapeAccounts.map(account =>
      `<option value="${Number(account.id)}">${escapeHtml(account.label || account.username || `Account #${account.id}`)}</option>`
    ).join("");
    select.value = Array.from(select.options).some(option => option.value === current) ? current : "auto";
  } catch (e) {}
}

async function startPageSearch() {
  setCollapsiblePanel("page-search", false);
  const keyword = document.getElementById("page-search-keyword").value.trim();
  const settings = getSharedScrapeSettings();
  if (!keyword) return showToast("Hãy nhập từ khóa cần tìm", "warning");
  setAppActivity({ type: "running", title: "Chuẩn bị tìm Fanpage", message: `Đang khởi động tìm kiếm “${keyword}”...` });
  try {
    const res = await fetch("/api/scrape/search/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword,
        account_mode: settings.accountMode,
        account_id: settings.accountId,
        limit: parseInt(document.getElementById("page-search-limit").value) || 30,
        min_followers: parseInt(document.getElementById("page-search-min-followers").value) || 0,
        sort_by: document.getElementById("page-search-sort").value
      })
    });
    const json = await res.json();
    if (!res.ok) return showToast(json.detail || "Không thể bắt đầu tìm kiếm", "error");
    state.pageSearchWasRunning = true;
    setFavoriteScanControls(true);
    state.pageSearchResults = [];
    renderPageSearchResults();
    document.getElementById("page-search-summary").textContent = "Đang khởi động...";
    showToast("Đã bắt đầu tìm Fanpage", "success");
  } catch (error) {
    showToast("Lỗi kết nối khi tìm Fanpage", "error");
  }
}

function formatFollowerCount(value, fallback = "") {
  const count = Number(value) || 0;
  return count > 0 ? new Intl.NumberFormat("vi-VN").format(count) : (fallback || "Không xác định");
}

function renderPageSearchResults() {
  const wrap = document.getElementById("page-search-results-wrap");
  const tbody = document.getElementById("page-search-results-tbody");
  wrap.style.display = state.pageSearchResults.length ? "block" : "none";
  tbody.innerHTML = state.pageSearchResults.map((page, index) => {
    const avatar = page.avatar_url
      ? `<img class="page-search-avatar" src="${escapeHtml(page.avatar_url)}" alt="" referrerpolicy="no-referrer">`
      : `<div class="page-search-avatar" style="display:grid;place-items:center;font-weight:800;">${escapeHtml((page.page_name || "?").slice(0, 1).toUpperCase())}</div>`;
    const starTitle = page.is_favorite ? "Đã lưu yêu thích" : "Lưu vào yêu thích";
    return `<tr>
      <td><input class="page-search-check" type="checkbox" value="${index}" ${page._selected ? "checked" : ""} ${page.is_favorite ? "disabled" : ""} onchange="setSearchPageSelected(${index}, this.checked)"></td>
      <td><button class="page-search-star ${page.is_favorite ? "saved" : ""}" title="${starTitle}" ${page.is_favorite ? "disabled" : `onclick="saveSearchFavorite(${index})"`}>${page.is_favorite ? "★" : "☆"}</button></td>
      <td><div style="display:flex;align-items:center;gap:9px;min-width:260px;">${avatar}<div>
        <div style="font-weight:750;">${escapeHtml(page.page_name)} ${page.verified ? '<span title="Đã xác minh" style="color:#0f8ec7;">✓</span>' : ""}</div>
        <div class="text-muted" style="max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(page.page_url)}">${escapeHtml(page.page_url)}</div>
      </div></div></td>
      <td style="font-weight:700;">${escapeHtml(formatFollowerCount(page.follower_count, page.followers_text))}</td>
      <td>${escapeHtml(page.category || "—")}</td>
      <td style="text-align:right;"><div style="display:flex;gap:5px;justify-content:flex-end;">
        <a class="btn btn-secondary btn-sm" href="${escapeHtml(page.page_url)}" target="_blank" rel="noopener">Mở Page</a>
        <button class="btn btn-teal btn-sm" onclick="prepareSearchPageScan(${index})">Đưa vào quét</button>
      </div></td>
    </tr>`;
  }).join("");
  updateSortIndicators("page_search", state.pageSearchSort);
}

function setSearchPageSelected(index, selected) {
  if (state.pageSearchResults[index]) state.pageSearchResults[index]._selected = Boolean(selected);
}

function applyPageSearchSort() {
  const { key, direction } = state.pageSearchSort;
  const numericKeys = ["follower_count", "verified"];
  state.pageSearchResults.sort((left, right) => {
    if (key === "relevance") return (left._rank || 0) - (right._rank || 0);
    if (key === "follower_count") {
      const leftUnknown = !(Number(left.follower_count) > 0);
      const rightUnknown = !(Number(right.follower_count) > 0);
      if (leftUnknown !== rightUnknown) return leftUnknown ? 1 : -1;
    }
    const compared = compareTableValues(left[key], right[key], direction, numericKeys.includes(key));
    return compared || (left._rank || 0) - (right._rank || 0);
  });
}

function setPageSearchSort(key) {
  state.pageSearchSort = cycleTableSort(
    state.pageSearchSort, key, ["follower_count", "verified"],
    { key: "relevance", direction: "desc" }
  );
  applyPageSearchSort();
  renderPageSearchResults();
}

async function loadPageSearchResults() {
  const res = await fetch("/api/scrape/search/results");
  const json = await res.json();
  if (!res.ok) return;
  state.pageSearchResults = (json.data || []).map((page, index) => ({
    ...page, _rank: index, _selected: false
  }));
  state.pageSearchSort = { key: "relevance", direction: "desc" };
  renderPageSearchResults();
  const suffix = json.error && json.error !== "Đã dừng" ? ` · ${json.error}` : "";
  document.getElementById("page-search-summary").textContent = `${state.pageSearchResults.length} kết quả${suffix}`;
}

function searchFavoritePayload(page) {
  const settings = getSharedScrapeSettings();
  const groupId = Number(document.getElementById("search-favorite-group")?.value) || null;
  return {
    page_url: page.page_url,
    page_name: page.page_name,
    account_id: settings.accountId,
    scan_limit: settings.scanLimit,
    page_uid: page.page_uid || "",
    follower_count: Number(page.follower_count) || 0,
    category: page.category || "",
    avatar_url: page.avatar_url || null,
    verified: Boolean(page.verified),
    group_ids: groupId ? [groupId] : []
  };
}

async function saveSearchFavorite(index, quiet = false) {
  const page = state.pageSearchResults[index];
  if (!page || page.is_favorite) return;
  try {
    await saveFavorite(searchFavoritePayload(page));
    page.is_favorite = true;
    page._selected = false;
    renderPageSearchResults();
    if (!quiet) showToast(`Đã lưu ${page.page_name} vào yêu thích`, "success");
  } catch (error) {
    if (!quiet) showToast(error.message, "error");
    throw error;
  }
}

async function saveSelectedSearchPages() {
  const indexes = state.pageSearchResults
    .map((page, index) => page._selected && !page.is_favorite ? index : -1)
    .filter(index => index >= 0);
  if (!indexes.length) return showToast("Hãy chọn ít nhất một Fanpage chưa lưu", "warning");
  let saved = 0;
  for (const index of indexes) {
    try { await saveSearchFavorite(index, true); saved += 1; } catch (_) {}
  }
  showToast(`Đã lưu ${saved}/${indexes.length} Fanpage`, saved ? "success" : "error");
}

function prepareSearchPageScan(index) {
  const page = state.pageSearchResults[index];
  if (!page) return;
  setCollapsiblePanel("quick-scrape", false);
  document.getElementById("scrape-url").value = page.page_url;
  document.getElementById("quick-scrape-card").scrollIntoView({ behavior: "smooth", block: "start" });
  showToast("Đã đưa Fanpage vào biểu mẫu quét nhanh", "info");
}

function favoriteGroupOptionMarkup(includeSpecial = false) {
  const custom = state.favoriteGroups.map(group =>
    `<option value="${Number(group.id)}">${escapeHtml(group.name)} (${Number(group.page_count) || 0})</option>`
  ).join("");
  return includeSpecial
    ? `<option value="all">Tất cả nhóm</option><option value="ungrouped">Chưa phân nhóm</option>${custom}`
    : custom;
}

function toggleFavoriteGroupMenu() {
  const menu = document.getElementById("favorite-group-menu");
  const trigger = document.getElementById("favorite-group-trigger");
  if (!menu) return;
  const isHidden = menu.hidden;
  if (isHidden) {
    refreshFavoriteGroupControls();
    menu.hidden = false;
    trigger?.setAttribute("aria-expanded", "true");
  } else {
    closeFavoriteGroupMenu();
  }
}

function closeFavoriteGroupMenu() {
  const menu = document.getElementById("favorite-group-menu");
  const trigger = document.getElementById("favorite-group-trigger");
  if (menu) menu.hidden = true;
  trigger?.setAttribute("aria-expanded", "false");
}

async function selectFavoriteGroupItem(filterValue) {
  const selectedIds = selectedVisibleFavoriteIds();
  const isCustomGroup = Number(filterValue) > 0;
  closeFavoriteGroupMenu();

  if (selectedIds.length > 0 && isCustomGroup) {
    try {
      const result = await favoriteGroupRequest("members", {
        group_id: Number(filterValue), favorite_ids: selectedIds, action: "add"
      });
      const group = state.favoriteGroups.find(item => Number(item.id) === Number(filterValue));
      showToast(`Đã gán ${selectedIds.length} Page vào nhóm “${group?.name || ""}”`, "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  state.favoriteGroupFilter = String(filterValue);
  try { localStorage.setItem(FAVORITE_GROUP_FILTER_STORAGE_KEY, state.favoriteGroupFilter); } catch (_) {}
  await loadFavoritePages();
}

function editFavoriteGroupById(groupId, event) {
  if (event) event.stopPropagation();
  const group = state.favoriteGroups.find(item => Number(item.id) === Number(groupId));
  if (!group) return showToast("Không tìm thấy nhóm cần đổi tên", "warning");
  closeFavoriteGroupMenu();
  openModal(
    "Chỉnh sửa nhóm Fanpage",
    favoriteGroupModalBody(group.name, group.color),
    `<button class="btn btn-secondary" onclick="closeModal()">Hủy</button><button class="btn btn-primary" onclick="submitFavoriteGroupModal(${Number(group.id)})">Lưu thay đổi</button>`
  );
  setTimeout(() => document.getElementById("favorite-group-modal-name")?.focus(), 0);
}

async function deleteFavoriteGroupById(groupId, event) {
  if (event) event.stopPropagation();
  const group = state.favoriteGroups.find(item => Number(item.id) === Number(groupId));
  if (!group) return showToast("Không tìm thấy nhóm cần xóa", "warning");
  if (!confirm(`Xóa nhóm “${group.name}”? Fanpage và lịch sử quét vẫn được giữ.`)) return;
  closeFavoriteGroupMenu();
  try {
    await favoriteGroupRequest("delete", { group_id: Number(group.id) });
    if (String(state.favoriteGroupFilter) === String(groupId)) {
      state.favoriteGroupFilter = "all";
      try { localStorage.setItem(FAVORITE_GROUP_FILTER_STORAGE_KEY, "all"); } catch (_) {}
    }
    await loadFavoritePages();
    showToast(`Đã xóa nhóm “${group.name}”`, "success");
  } catch (error) { showToast(error.message, "error"); }
}

async function removeSelectedFromCurrentGroup() {
  closeFavoriteGroupMenu();
  const selectedIds = selectedVisibleFavoriteIds();
  if (!selectedIds.length) return showToast("Hãy chọn ít nhất một Fanpage", "warning");
  const currentGroupId = Number(state.favoriteGroupFilter);
  if (!currentGroupId) {
    return showToast("Hãy lọc xem nhóm cụ thể trước khi bỏ Page khỏi nhóm", "warning");
  }
  try {
    const result = await favoriteGroupRequest("members", {
      group_id: currentGroupId, favorite_ids: selectedIds, action: "remove"
    });
    await loadFavoritePages();
    showToast(`Đã bỏ ${result.changed} Page khỏi nhóm`, "success");
  } catch (error) { showToast(error.message, "error"); }
}

function refreshFavoriteGroupControls() {
  const triggerLabel = document.getElementById("favorite-group-trigger-label");
  const menuList = document.getElementById("favorite-group-menu-list");
  const assignHint = document.getElementById("favorite-group-assign-hint");
  const hintCount = document.getElementById("favorite-group-hint-count");
  const removeWrap = document.getElementById("favorite-group-remove-wrap");

  const totalPages = state.favoritePages.length;
  const ungroupedCount = state.favoritePages.filter(p => !(p.groups || []).length).length;
  const currentFilter = state.favoriteGroupFilter || "all";
  const selectedIds = selectedVisibleFavoriteIds();
  const currentGroup = state.favoriteGroups.find(g => String(g.id) === String(currentFilter));

  if (triggerLabel) {
    if (currentFilter === "all") {
      triggerLabel.textContent = `📁 Tất cả nhóm (${totalPages})`;
    } else if (currentFilter === "ungrouped") {
      triggerLabel.textContent = `⚪ Chưa phân nhóm (${ungroupedCount})`;
    } else if (currentGroup) {
      triggerLabel.textContent = `🏷️ ${currentGroup.name} (${Number(currentGroup.page_count) || 0})`;
    } else {
      triggerLabel.textContent = `📁 Tất cả nhóm (${totalPages})`;
    }
  }

  if (assignHint && hintCount) {
    if (selectedIds.length > 0) {
      assignHint.hidden = false;
      hintCount.textContent = String(selectedIds.length);
    } else {
      assignHint.hidden = true;
    }
  }

  if (removeWrap) {
    removeWrap.hidden = !(selectedIds.length > 0 && Number(currentFilter) > 0);
  }

  if (menuList) {
    const isAllActive = currentFilter === "all" ? "active" : "";
    const isUngroupedActive = currentFilter === "ungrouped" ? "active" : "";

    let html = `
      <div class="favorite-group-menu-item ${isAllActive}" onclick="selectFavoriteGroupItem('all')">
        <div class="favorite-group-item-main">
          <span>📁</span>
          <span class="favorite-group-item-name">Tất cả nhóm</span>
        </div>
        <span class="favorite-group-item-count">${totalPages}</span>
      </div>
      <div class="favorite-group-menu-item ${isUngroupedActive}" onclick="selectFavoriteGroupItem('ungrouped')">
        <div class="favorite-group-item-main">
          <span>⚪</span>
          <span class="favorite-group-item-name">Chưa phân nhóm</span>
        </div>
        <span class="favorite-group-item-count">${ungroupedCount}</span>
      </div>
    `;

    if (state.favoriteGroups.length > 0) {
      html += `<div class="favorite-group-menu-divider"></div>`;
      html += state.favoriteGroups.map(group => {
        const isActive = String(group.id) === String(currentFilter) ? "active" : "";
        const color = group.color || "#0f766e";
        const count = Number(group.page_count) || 0;
        return `
          <div class="favorite-group-menu-item ${isActive}" onclick="selectFavoriteGroupItem(${Number(group.id)})">
            <div class="favorite-group-item-main" title="${escapeHtml(group.name)}">
              <span class="favorite-group-dot" style="background-color:${escapeHtml(color)};"></span>
              <span class="favorite-group-item-name">${escapeHtml(group.name)}</span>
            </div>
            <span class="favorite-group-item-count">${count}</span>
            <div class="favorite-group-item-actions">
              <button type="button" class="favorite-group-action-icon" title="Đổi tên/màu nhóm" onclick="editFavoriteGroupById(${Number(group.id)}, event)">✏️</button>
              <button type="button" class="favorite-group-action-icon delete" title="Xóa nhóm" onclick="deleteFavoriteGroupById(${Number(group.id)}, event)">🗑️</button>
            </div>
          </div>
        `;
      }).join("");
    }

    menuList.innerHTML = html;
  }

  ["quick-favorite-group", "search-favorite-group"].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">Chưa phân nhóm</option>${favoriteGroupOptionMarkup(false)}`;
    if (Array.from(select.options).some(option => option.value === current)) select.value = current;
  });
}

async function loadFavoriteGroups() {
  try {
    const res = await fetch("/api/scrape/favorites/groups");
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || "Không thể tải nhóm");
    state.favoriteGroups = json.data || [];
    if (!state.favoriteGroupFilter || state.favoriteGroupFilter === "all") {
      try { state.favoriteGroupFilter = localStorage.getItem(FAVORITE_GROUP_FILTER_STORAGE_KEY) || "all"; } catch (_) {}
    }
    refreshFavoriteGroupControls();
  } catch (_) {
    showToast("Không thể tải nhóm Fanpage", "error");
  }
}

async function loadFavoritePages() {
  try {
    const [res] = await Promise.all([
      fetch("/api/scrape/favorites"),
      loadFavoriteGroups(),
    ]);
    const json = await res.json();
    if (res.ok) {
      const selected = new Map(state.favoritePages.map(page => [Number(page.id), page._selected !== false]));
      state.favoritePages = (json.data || []).map(page => ({
        ...page, _selected: selected.has(Number(page.id)) ? selected.get(Number(page.id)) : true
      }));
      applyFavoriteSort();
      renderFavoritePages();
    }
  } catch (e) {
    showToast("Không thể tải Fanpage yêu thích", "error");
  }
}

function favoriteStatusClass(status) {
  if (status === "Thành công") return "badge-green";
  if (["Lỗi", "Không có dữ liệu"].includes(status)) return "badge-red";
  if (["Chưa hoàn tất", "Đã dừng"].includes(status)) return "badge-amber";
  return "badge-teal";
}

function getVisibleFavoritePages() {
  const filter = state.favoriteGroupFilter || "all";
  const query = state.favoritePageSearch || "";
  return state.favoritePages.filter(page => {
    const groups = Array.isArray(page.groups) ? page.groups : [];
    const inGroup = filter === "all"
      || (filter === "ungrouped" && !groups.length)
      || (Number(filter) > 0 && groups.some(group => Number(group.id) === Number(filter)));
    if (!inGroup) return false;
    if (!query) return true;
    return `${page.page_name || ""} ${page.page_url || ""}`.toLocaleLowerCase("vi").includes(query);
  });
}

function renderFavoritePages() {
  const tbody = document.getElementById("favorite-pages-tbody");
  const summary = document.getElementById("favorite-scan-summary");
  const visiblePages = getVisibleFavoritePages();
  const group = state.favoriteGroups.find(item => Number(item.id) === Number(state.favoriteGroupFilter));
  const context = group ? group.name : (state.favoriteGroupFilter === "ungrouped" ? "Chưa phân nhóm" : "Tất cả");
  summary.textContent = state.favoriteGroupFilter === "all" && !state.favoritePageSearch
    ? `${state.favoritePages.length} Fanpage`
    : `${visiblePages.length}/${state.favoritePages.length} · ${context}`;
  const selectAll = document.getElementById("favorite-select-all");
  if (selectAll) {
    selectAll.checked = Boolean(visiblePages.length) && visiblePages.every(page => page._selected !== false);
    selectAll.indeterminate = visiblePages.some(page => page._selected !== false) && !selectAll.checked;
  }
  if (!visiblePages.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted" style="padding:28px; text-align:center;">Chưa có Fanpage yêu thích</td></tr>`;
    return;
  }
  tbody.innerHTML = visiblePages.map(page => {
    const label = page.page_name || page.page_url.replace(/^https?:\/\/(www\.)?facebook\.com\//, "");
    const pageUrl = safeFacebookPostUrl(page.page_url);
    const lastScan = page.last_successful_scan_at || "Chưa quét";
    const error = page.last_error ? `<div class="text-muted" title="${escapeHtml(page.last_error)}" style="max-width:210px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(page.last_error)}</div>` : "";
    const resultLabel = String(page.last_status || "").includes("bài cũ") ? "bài cũ" : "bài mới";
    const groupTags = (page.groups || []).length
      ? `<div class="favorite-group-tags">${page.groups.map(group => `<span class="favorite-group-tag" style="--group-color:${escapeHtml(group.color || "#0f766e")}">${escapeHtml(group.name)}</span>`).join("")}</div>`
      : `<div class="favorite-group-tags"><span class="favorite-group-tag" style="--group-color:#94a3b8">Chưa phân nhóm</span></div>`;
    return `
      <tr style="border-bottom:1px solid var(--border-subtle);">
        <td style="padding:10px;"><input class="favorite-page-check" type="checkbox" value="${Number(page.id)}" ${page._selected !== false ? "checked" : ""} onchange="setFavoriteSelected(${Number(page.id)}, this.checked)"></td>
        <td style="padding:10px;">
          <div style="font-weight:700;">⭐ ${pageUrl
            ? `<a class="favorite-page-link" href="${escapeHtml(pageUrl)}" target="_blank" rel="noopener" title="Mở Fanpage trong tab mới">${escapeHtml(label)}</a>`
            : escapeHtml(label)}</div>
          <div class="text-muted" style="font-size:11.5px; max-width:310px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(page.page_url)}">${escapeHtml(page.page_url)}</div>
          ${groupTags}
        </td>
        <td style="padding:10px; font-weight:700;">${escapeHtml(formatFollowerCount(page.follower_count))}</td>
        <td style="padding:10px;">${escapeHtml(lastScan)}</td>
        <td style="padding:10px;">
          <span class="badge ${favoriteStatusClass(page.last_status)}">${escapeHtml(page.last_status)}</span>
          <div style="margin-top:4px;">+${Number(page.last_new_posts_count) || 0} ${resultLabel}</div>
          <div class="text-muted" style="font-size:11px;">Đã mở rộng lịch sử: ${Number(page.archive_scanned_count) || 0} bài</div>
          ${error}
        </td>
        <td style="padding:10px; text-align:right;">
          <div style="display:flex; justify-content:flex-end; gap:5px; flex-wrap:wrap;">
            <button class="btn btn-teal btn-sm" onclick="scanFavoritePages([${Number(page.id)}])">Quét mới</button>
            <button class="btn btn-secondary btn-sm" onclick="scanFavoritePages([${Number(page.id)}], 'older')">Quét cũ</button>
            <button class="btn btn-secondary btn-sm" onclick="resetFavoritePage(${Number(page.id)})">Quét từ đầu</button>
            <button class="btn btn-danger btn-sm" onclick="deleteFavoritePageUi(${Number(page.id)})">Bỏ</button>
          </div>
        </td>
      </tr>`;
  }).join("");
  updateSortIndicators("favorites", state.favoriteSort);
  updateFavoriteBulkButtons();
}

function updateFavoriteBulkButtons() {
  const selectedIds = selectedVisibleFavoriteIds();
  const selCount = selectedIds.length;
  const countSuffix = selCount > 0 ? ` (${selCount})` : "";

  const btnNew = document.getElementById("btn-scan-selected-favorites");
  if (btnNew) btnNew.textContent = `Quét bài mới${countSuffix}`;

  const btnOlder = document.getElementById("btn-scan-older-favorites");
  if (btnOlder) btnOlder.textContent = `Quét bài cũ${countSuffix}`;

  const btnReset = document.getElementById("btn-reset-selected-favorites");
  if (btnReset) btnReset.textContent = `Quét từ đầu${countSuffix}`;

  const btnDelete = document.getElementById("btn-delete-selected-favorites");
  if (btnDelete) btnDelete.textContent = `🗑 Xóa${countSuffix}`;

  const visiblePages = getVisibleFavoritePages();
  const selectAll = document.getElementById("favorite-select-all");
  if (selectAll) {
    selectAll.checked = Boolean(visiblePages.length) && visiblePages.every(page => page._selected !== false);
    selectAll.indeterminate = visiblePages.some(page => page._selected !== false) && !selectAll.checked;
  }

  const assignHint = document.getElementById("favorite-group-assign-hint");
  const hintCount = document.getElementById("favorite-group-hint-count");
  const removeWrap = document.getElementById("favorite-group-remove-wrap");
  if (assignHint && hintCount) {
    assignHint.hidden = selCount === 0;
    hintCount.textContent = String(selCount);
  }
  if (removeWrap) {
    removeWrap.hidden = !(selCount > 0 && Number(state.favoriteGroupFilter) > 0);
  }
}

function setFavoriteSelected(favoriteId, selected) {
  const page = state.favoritePages.find(item => Number(item.id) === Number(favoriteId));
  if (page) page._selected = Boolean(selected);
  updateFavoriteBulkButtons();
}

function selectedVisibleFavoriteIds() {
  const visibleIds = new Set(getVisibleFavoritePages().map(page => Number(page.id)));
  return state.favoritePages
    .filter(page => visibleIds.has(Number(page.id)) && page._selected !== false)
    .map(page => Number(page.id));
}

async function bulkResetFavoritePagesUi() {
  const ids = selectedVisibleFavoriteIds();
  if (!ids.length) return showToast("Vui lòng chọn ít nhất một Fanpage để quét từ đầu", "warning");
  if (!confirm(`Quét từ đầu sẽ xóa mốc quét của ${ids.length} Fanpage đã chọn và bắt đầu quét lại ngay. Tiếp tục?`)) return;
  try {
    const res = await fetch("/api/scrape/favorites/batch-reset-cursor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite_ids: ids })
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || "Không thể đặt lại mốc quét");
    await scanFavoritePages(ids);
  } catch (error) { showToast(error.message, "error"); }
}

async function bulkDeleteFavoritePagesUi() {
  const ids = selectedVisibleFavoriteIds();
  if (!ids.length) return showToast("Vui lòng chọn ít nhất một Fanpage để xóa", "warning");
  if (!confirm(`Bỏ ${ids.length} Fanpage đã chọn khỏi danh sách yêu thích? Dữ liệu bài viết vẫn được giữ.`)) return;
  try {
    const res = await fetch("/api/scrape/favorites/batch-delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite_ids: ids })
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || "Không thể xóa Fanpage");
    showToast(`Đã bỏ ${json.count || ids.length} Fanpage khỏi yêu thích`, "success");
    await loadFavoritePages();
  } catch (error) { showToast(error.message, "error"); }
}

async function favoriteGroupRequest(path, payload) {
  const res = await fetch(`/api/scrape/favorites/groups/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || "Không thể cập nhật nhóm Fanpage");
  return json;
}

function favoriteGroupModalBody(name = "", color = "#0f766e") {
  return `<div style="display:grid;gap:14px;">
    <label style="display:grid;gap:6px;font-weight:700;font-size:12.5px;">Tên nhóm
      <input id="favorite-group-modal-name" maxlength="80" value="${escapeHtml(name)}" placeholder="Ví dụ: In ảnh, Đối thủ, Mẹ và Bé">
    </label>
    <label style="display:grid;gap:6px;font-weight:700;font-size:12.5px;">Màu đại diện
      <input id="favorite-group-modal-color" type="color" value="${escapeHtml(color || "#0f766e")}" style="width:100%;height:42px;padding:4px;">
    </label>
    <div class="text-muted" style="font-size:11.5px;">Một Fanpage có thể nằm trong nhiều nhóm. Việc đổi nhóm không ảnh hưởng mốc quét.</div>
  </div>`;
}

function createFavoriteGroupUi() {
  openModal(
    "Tạo nhóm Fanpage",
    favoriteGroupModalBody(),
    `<button class="btn btn-secondary" onclick="closeModal()">Hủy</button><button class="btn btn-primary" onclick="submitFavoriteGroupModal(0)">Tạo nhóm</button>`
  );
  setTimeout(() => document.getElementById("favorite-group-modal-name")?.focus(), 0);
}

function renameFavoriteGroupUi() {
  const group = state.favoriteGroups.find(item => Number(item.id) === Number(state.favoriteGroupFilter));
  if (!group) return showToast("Hãy chọn một nhóm cần đổi tên", "warning");
  openModal(
    "Chỉnh sửa nhóm Fanpage",
    favoriteGroupModalBody(group.name, group.color),
    `<button class="btn btn-secondary" onclick="closeModal()">Hủy</button><button class="btn btn-primary" onclick="submitFavoriteGroupModal(${Number(group.id)})">Lưu thay đổi</button>`
  );
  setTimeout(() => document.getElementById("favorite-group-modal-name")?.focus(), 0);
}

async function submitFavoriteGroupModal(groupId) {
  const name = document.getElementById("favorite-group-modal-name")?.value.trim();
  const color = document.getElementById("favorite-group-modal-color")?.value || "#0f766e";
  if (!name) return showToast("Tên nhóm không được để trống", "warning");
  try {
    const result = groupId
      ? await favoriteGroupRequest("update", { group_id: Number(groupId), name, color })
      : await favoriteGroupRequest("create", { name, color });
    const selectedId = groupId || result.id;
    state.favoriteGroupFilter = String(selectedId);
    try { localStorage.setItem(FAVORITE_GROUP_FILTER_STORAGE_KEY, state.favoriteGroupFilter); } catch (_) {}
    closeModal();
    await loadFavoritePages();
    document.getElementById("favorite-group-target").value = String(selectedId);
    showToast(groupId ? `Đã cập nhật nhóm “${name}”` : `Đã tạo nhóm “${name}”`, "success");
  } catch (error) { showToast(error.message, "error"); }
}

async function deleteFavoriteGroupUi() {
  const group = state.favoriteGroups.find(item => Number(item.id) === Number(state.favoriteGroupFilter));
  if (!group) return showToast("Hãy chọn một nhóm cần xóa", "warning");
  if (!confirm(`Xóa nhóm “${group.name}”? Fanpage và lịch sử quét vẫn được giữ.`)) return;
  try {
    await favoriteGroupRequest("delete", { group_id: Number(group.id) });
    state.favoriteGroupFilter = "all";
    try { localStorage.setItem(FAVORITE_GROUP_FILTER_STORAGE_KEY, "all"); } catch (_) {}
    await loadFavoritePages();
    showToast(`Đã xóa nhóm “${group.name}”`, "success");
  } catch (error) { showToast(error.message, "error"); }
}

async function updateSelectedFavoriteGroup(action) {
  const groupId = Number(document.getElementById("favorite-group-target").value);
  if (!groupId) return showToast("Hãy chọn nhóm đích", "warning");
  const favoriteIds = selectedVisibleFavoriteIds();
  if (!favoriteIds.length) return showToast("Hãy chọn ít nhất một Fanpage đang hiển thị", "warning");
  try {
    const result = await favoriteGroupRequest("members", {
      group_id: groupId, favorite_ids: favoriteIds, action
    });
    await loadFavoritePages();
    showToast(
      action === "add" ? `Đã thêm ${result.changed} Page vào nhóm` : `Đã bỏ ${result.changed} Page khỏi nhóm`,
      "success"
    );
  } catch (error) { showToast(error.message, "error"); }
}

function scanCurrentFavoriteGroup() {
  const groupId = Number(state.favoriteGroupFilter);
  if (!groupId) return showToast("Hãy chọn một nhóm cụ thể để quét", "warning");
  const ids = state.favoritePages
    .filter(page => (page.groups || []).some(group => Number(group.id) === groupId))
    .map(page => Number(page.id));
  if (!ids.length) return showToast("Nhóm này chưa có Fanpage", "warning");
  scanFavoritePages(ids);
}

function applyFavoriteSort() {
  const { key, direction } = state.favoriteSort;
  const numericKeys = ["follower_count", "last_new_posts_count", "scan_limit"];
  state.favoritePages.sort((left, right) => {
    if (key === "follower_count") {
      const leftUnknown = !(Number(left.follower_count) > 0);
      const rightUnknown = !(Number(right.follower_count) > 0);
      if (leftUnknown !== rightUnknown) return leftUnknown ? 1 : -1;
    }
    const compared = compareTableValues(left[key], right[key], direction, numericKeys.includes(key));
    return compared || compareTableValues(left.page_name || left.page_url, right.page_name || right.page_url, "asc");
  });
}

function setFavoriteSort(key) {
  state.favoriteSort = cycleTableSort(
    state.favoriteSort, key,
    ["follower_count", "last_new_posts_count", "scan_limit", "last_successful_scan_at"],
    { key: "page_name", direction: "asc" }
  );
  applyFavoriteSort();
  renderFavoritePages();
}

async function saveFavorite(payload) {
  const res = await fetch("/api/scrape/favorites/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || "Không thể lưu Fanpage");
  await loadFavoritePages();
  return json;
}

async function saveFavoriteFromForm() {
  const pageUrls = normalizePageInputLines(document.getElementById("scrape-url").value);
  if (!pageUrls.length) {
    showToast("Hãy nhập URL Fanpage trước", "warning");
    return;
  }
  const settings = getSharedScrapeSettings();
  const groupId = Number(document.getElementById("quick-favorite-group")?.value) || null;
  let saved = 0;
  try {
    for (const pageUrl of pageUrls) {
      await saveFavorite({
        page_url: pageUrl, scan_limit: settings.scanLimit, account_id: settings.accountId,
        group_ids: groupId ? [groupId] : []
      });
      saved += 1;
    }
    showToast(`Đã lưu ${saved} Fanpage yêu thích`, "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function scanFavoritePages(ids, scanDirection = "new") {
  setCollapsiblePanel("favorite-pages", false);
  const settings = getSharedScrapeSettings();
  setAppActivity({
    type: "running",
    title: "Chuẩn bị quét Fanpage",
    message: `Đang xếp hàng ${ids.length} Fanpage ${scanDirection === "older" ? "quét bài cũ" : "quét bài mới"}...`
  });
  try {
    const res = await fetch("/api/scrape/favorites/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        favorite_ids: ids, account_mode: settings.accountMode, account_id: settings.accountId,
        max_concurrency: settings.maxConcurrency, scan_limit: settings.scanLimit,
        download_media: settings.autoDownload,
        scan_direction: scanDirection,
        delay_mode: settings.delayMode
      })
    });
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể bắt đầu quét", "error");
      return;
    }
    state.favoriteScanWasRunning = true;
    setFavoriteScanControls(true);
    showToast(
      `Đã xếp hàng ${json.queued} Fanpage ${scanDirection === "older" ? "quét bài cũ" : "quét bài mới"} · ${json.account_label} · ${json.workers} luồng`,
      "success"
    );
    loadFavoritePages();
  } catch (e) {
    showToast("Lỗi kết nối khi bắt đầu hàng đợi", "error");
  }
}

function setFavoriteScanControls(running) {
  ["scrape-common-account", "scrape-common-concurrency", "scrape-common-delay", "scrape-common-limit", "scrape-auto-download", "btn-start-scrape", "btn-start-page-search", "btn-scan-selected-favorites", "btn-scan-older-favorites", "btn-reset-selected-favorites", "btn-delete-selected-favorites", "favorite-group-trigger", "btn-remove-selected-from-group", "btn-create-favorite-group"]
    .forEach(id => {
      const element = document.getElementById(id);
      if (element) element.disabled = Boolean(running);
    });
  const stopAll = document.getElementById("btn-stop-all-favorites");
  if (stopAll) stopAll.disabled = !running;
  if (!running) refreshFavoriteGroupControls();
}

function favoriteWorkerStatusClass(status) {
  if (status === "Hoàn tất") return "badge-green";
  if (["Đã dừng", "Đang dừng"].includes(status)) return "badge-amber";
  if (["Lỗi", "Không sẵn sàng"].includes(status)) return "badge-red";
  return "badge-teal";
}

function renderFavoriteWorkers(workers, isRunning) {
  const panel = document.getElementById("favorite-workers-panel");
  const grid = document.getElementById("favorite-workers-grid");
  if (!panel || !grid) return;
  panel.hidden = !workers.length;
  grid.innerHTML = workers.map(worker => {
    const status = worker.status || "Đang chờ";
    const canStop = isRunning && !["Hoàn tất", "Đã dừng", "Lỗi", "Không sẵn sàng"].includes(status);
    return `<div class="favorite-worker-card">
      <div class="favorite-worker-card-top">
        <strong>${escapeHtml(worker.account_label || "Profile mặc định")}</strong>
        <span class="badge ${favoriteWorkerStatusClass(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="favorite-worker-page" title="${escapeHtml(worker.current_page || "")}">
        ${escapeHtml(worker.current_page || (status === "Đang chờ" ? "Đang chờ đến lượt" : "Không có Page đang quét"))}
      </div>
      <div class="favorite-worker-card-progress">
        <span>${Number(worker.queue_completed) || 0}/${Number(worker.queue_total) || 0} Page · ${Number(worker.posts_found) || 0} bài đang thấy · +${Number(worker.new_posts) || 0} bài mới</span>
        ${canStop ? `<button class="btn btn-secondary btn-sm" onclick="stopFavoriteWorker('${encodeInlineArg(worker.worker_id)}')">Dừng</button>` : ""}
      </div>
      ${worker.error ? `<div class="text-muted" style="font-size:10.5px;margin-top:6px;color:var(--danger-red);">${escapeHtml(worker.error)}</div>` : ""}
    </div>`;
  }).join("");
}

async function stopFavoriteWorker(encodedWorkerId) {
  const workerId = decodeURIComponent(encodedWorkerId);
  try {
    const res = await fetch("/api/scrape/favorites/stop-worker", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ worker_id: workerId })
    });
    const json = await res.json();
    showToast(res.ok ? "Đã gửi lệnh dừng Account" : (json.detail || "Không thể dừng Account"), res.ok ? "info" : "error");
  } catch (_) { showToast("Lỗi kết nối khi dừng Account", "error"); }
}

async function stopAllFavoriteScans() {
  try {
    await fetch("/api/scrape/stop", { method: "POST" });
    showToast("Đã gửi lệnh dừng tất cả hàng đợi", "info");
  } catch (_) { showToast("Lỗi kết nối khi dừng hàng đợi", "error"); }
}

async function favoriteAction(path, favoriteId) {
  const res = await fetch(`/api/scrape/favorites/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ favorite_id: favoriteId })
  });
  const json = await res.json();
  if (!res.ok) throw new Error(json.detail || "Không thể cập nhật Fanpage");
  await loadFavoritePages();
}

async function resetFavoritePage(favoriteId) {
  if (!confirm("Quét từ đầu sẽ xóa mốc hiện tại và bắt đầu quét lại ngay. Tiếp tục?")) return;
  try {
    await favoriteAction("reset-cursor", favoriteId);
    await scanFavoritePages([favoriteId]);
  } catch (error) { showToast(error.message, "error"); }
}

async function deleteFavoritePageUi(favoriteId) {
  if (!confirm("Bỏ Fanpage khỏi danh sách yêu thích? Dữ liệu bài viết vẫn được giữ.")) return;
  try {
    await favoriteAction("delete", favoriteId);
    showToast("Đã bỏ Fanpage yêu thích", "success");
  } catch (error) { showToast(error.message, "error"); }
}

async function pollFavoriteScanStatus() {
  if (state.activeTab !== "tab-scraper") return;
  try {
    const res = await fetch("/api/scrape/status");
    const json = await res.json();
    if (!res.ok) return;
    const data = json.data;
    const summary = document.getElementById("favorite-scan-summary");
    if (data.is_running && data.task_type === "page_search") {
      state.pageSearchWasRunning = true;
      setFavoriteScanControls(true);
      document.getElementById("page-search-summary").textContent = `Đang tìm · ${data.posts_found}/${data.queue_total}`;
    } else if (state.pageSearchWasRunning && data.task_type === "page_search") {
      state.pageSearchWasRunning = false;
      setFavoriteScanControls(false);
      await loadPageSearchResults();
    } else if (data.is_running && ["favorites", "quick_batch"].includes(data.task_type)) {
      state.favoriteScanWasRunning = true;
      setFavoriteScanControls(true);
      renderFavoriteWorkers(data.workers || [], true);
      const activeWorkers = (data.workers || []).filter(worker => !["Hoàn tất", "Đã dừng", "Lỗi"].includes(worker.status)).length;
      if (data.task_type === "favorites") {
        summary.textContent = `Đang quét ${data.queue_completed}/${data.queue_total} · ${activeWorkers} Account · +${data.new_posts} bài`;
      }
    } else if (state.favoriteScanWasRunning) {
      state.favoriteScanWasRunning = false;
      setFavoriteScanControls(false);
      renderFavoriteWorkers(data.workers || [], false);
      await loadFavoritePages();
    }
  } catch (e) {}
}

// ─── Tab 3: Spy Studio (Kho Bài Viết) ────────────────────────────────────────

async function loadSpyPages() {
  try {
    const res = await fetch("/api/spy/pages");
    const json = await res.json();
    if (json.status === "success") {
      state.scrapedPages = json.data;
      renderSpyPageDropdown();
      await loadSpyPosts();
    }
  } catch (e) {}
}

function syncSpySelectedPagesFromDropdown() {
  const select = document.getElementById("spy-page-filter");
  const val = select ? select.value : "";
  if (!val) {
    state.selectedPageNames = state.scrapedPages.map(p => p.page_name);
    state.selectedPageUrls = state.scrapedPages.map(p => p.page_url);
  } else {
    state.selectedPageNames = [val];
    const pageObj = state.scrapedPages.find(p => p.page_name === val);
    state.selectedPageUrls = pageObj ? [pageObj.page_url] : [];
  }
}

function renderSpyPageDropdown() {
  const select = document.getElementById("spy-page-filter");
  if (!select) return;

  const previousValue = select.value;
  select.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = `📄 Tất cả Page (${state.scrapedPages.length})`;
  select.appendChild(defaultOption);

  state.scrapedPages.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.page_name;
    const count = Number(p.post_count) || 0;
    opt.textContent = `${p.page_name} (${count})`;
    select.appendChild(opt);
  });

  const validValues = ["", ...state.scrapedPages.map(p => p.page_name)];
  if (validValues.includes(previousValue)) {
    select.value = previousValue;
  } else {
    select.value = "";
  }

  syncSpySelectedPagesFromDropdown();
}

let spyPostsAbortController = null;

async function loadSpyPosts() {
  const requestId = ++state.spyPostsRequest;
  if (spyPostsAbortController) {
    spyPostsAbortController.abort();
    spyPostsAbortController = null;
  }
  if (!state.selectedPageNames.length) {
    state.spyPosts = [];
    state.selectedSpyPostIds.clear();
    document.getElementById("spy-posts-grid").innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px;" class="text-muted">Chưa chọn page nào để hiển thị</div>`;
    document.getElementById("spy-posts-tbody").innerHTML = "";
    syncSpyPostSelectionUi();
    return;
  }

  const mode = document.getElementById("spy-mode").value;
  const postType = document.getElementById("spy-post-type").value;
  const dlStatus = document.getElementById("spy-dl-status").value;
  const query = document.getElementById("spy-search").value;
  const controller = new AbortController();
  spyPostsAbortController = controller;

  try {
    const res = await fetch("/api/spy/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        page_names: state.selectedPageNames,
        mode: mode,
        post_type: postType,
        download_status: dlStatus,
        query: query,
        sort_by: state.spySort.key,
        sort_order: state.spySort.direction
      })
    });
    const json = await res.json();
    if (requestId === state.spyPostsRequest && json.status === "success") {
      state.spyPosts = json.data;
      state.selectedSpyPostIds.clear();
      renderSpyPosts();
      syncSpyPostSelectionUi();
    }
  } catch (e) {
    if (e.name !== "AbortError") console.error("Không tải được danh sách bài viết:", e);
  } finally {
    if (requestId === state.spyPostsRequest && spyPostsAbortController === controller) {
      spyPostsAbortController = null;
    }
  }
}

function setSpySort(key) {
  state.spySort = cycleTableSort(
    state.spySort, key,
    ["date", "engagement", "comments", "shares", "view_count", "total_engagement", "downloaded"],
    { key: "date", direction: "desc" }
  );
  const modeBySort = {
    "date:desc": "newest", "date:asc": "oldest",
    "total_engagement:desc": "top_engagement",
    "engagement:desc": "top_reactions", "comments:desc": "top_comments",
    "shares:desc": "top_shares", "view_count:desc": "top_views"
  };
  const matchingMode = modeBySort[`${state.spySort.key}:${state.spySort.direction}`];
  if (matchingMode) document.getElementById("spy-mode").value = matchingMode;
  updateSortIndicators("spy", state.spySort);
  loadSpyPosts();
}

function applySpyModeSelection() {
  const modes = {
    newest: { key: "date", direction: "desc" },
    oldest: { key: "date", direction: "asc" },
    top_engagement: { key: "total_engagement", direction: "desc" },
    top_reactions: { key: "engagement", direction: "desc" },
    top_comments: { key: "comments", direction: "desc" },
    top_shares: { key: "shares", direction: "desc" },
    top_views: { key: "view_count", direction: "desc" }
  };
  state.spySort = modes[document.getElementById("spy-mode").value] || modes.newest;
  updateSortIndicators("spy", state.spySort);
  loadSpyPosts();
}

let spyMediaObserver = null;

function safeFacebookPostUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    const host = parsed.hostname.toLowerCase();
    return parsed.protocol === "https:" && (host === "facebook.com" || host.endsWith(".facebook.com"))
      ? parsed.href : "";
  } catch (_) {
    return "";
  }
}

function safeFacebookPreviewUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    const host = parsed.hostname.toLowerCase();
    return parsed.protocol === "https:" && (host === "fbcdn.net" || host.endsWith(".fbcdn.net"))
      ? parsed.href : "";
  } catch (_) {
    return "";
  }
}

function spyMediaSource(post) {
  if (post.preview_path) {
    return {
      src: `/media-preview?path=${encodeURIComponent(post.preview_path)}`,
      kind: post.preview_kind === "video" ? "video" : "image",
      local: true
    };
  }
  const remote = safeFacebookPreviewUrl(post.media_preview_url);
  return remote ? { src: remote, kind: "image", local: false } : null;
}

function spyMediaPreviewMarkup(post, index, context) {
  const source = spyMediaSource(post);
  const isVideo = post.post_type === "Video" || source?.kind === "video";
  const mediaCount = Math.max(0, Number(post.media_count) || 0);
  const label = source ? "Xem media" : "Chưa có hình xem trước";
  const media = source
    ? (source.kind === "video"
      ? `<video class="spy-lazy-media" data-src="${escapeHtml(source.src)}" muted preload="metadata" playsinline onerror="handleSpyMediaError(this)"></video>`
      : `<img class="spy-lazy-media" data-src="${escapeHtml(source.src)}" loading="lazy" alt="" referrerpolicy="no-referrer" onerror="handleSpyMediaError(this)">`)
    : "";
  return `<button type="button" class="spy-media-preview spy-media-preview-${context}" onclick="openSpyMedia(${index})" title="${label}" aria-label="${label}">
    ${media}
    <span class="spy-media-fallback" ${source ? "hidden" : ""}><span>${isVideo ? "🎥" : (post.post_type === "Ảnh" ? "🖼️" : "📄")}</span><small>${source ? "Không tải được" : "Chưa có preview"}</small></span>
    ${isVideo ? '<span class="spy-media-play">▶</span>' : ""}
    ${mediaCount > 1 ? `<span class="spy-media-count">+${mediaCount - 1}</span>` : ""}
  </button>`;
}

function handleSpyMediaError(element) {
  element.hidden = true;
  const preview = element.closest(".spy-media-preview");
  const fallback = preview?.querySelector(".spy-media-fallback");
  if (fallback) fallback.hidden = false;
}

function observeSpyLazyMedia() {
  if (spyMediaObserver) spyMediaObserver.disconnect();
  const media = Array.from(document.querySelectorAll(".spy-lazy-media[data-src]"));
  const load = element => {
    if (!element.src) element.src = element.dataset.src;
    element.removeAttribute("data-src");
  };
  if (!("IntersectionObserver" in window)) {
    media.forEach(load);
    return;
  }
  spyMediaObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      load(entry.target);
      spyMediaObserver.unobserve(entry.target);
    });
  }, { rootMargin: "180px 0px" });
  media.forEach(element => spyMediaObserver.observe(element));
}

function spyPostRatingMarkup(post) {
  const rating = Math.max(0, Math.min(5, Number(post.rating) || 0));
  return `<div class="spy-rating" aria-label="Xếp hạng bài viết" title="Phím 1–5 để xếp hạng">
    ${[1, 2, 3, 4, 5].map(value => `<button type="button" class="spy-rating-star ${value <= rating ? "active" : ""}" aria-label="${value} sao" aria-pressed="${value <= rating}" onclick="rateCurrentSpyPost(${value})">★</button>`).join("")}
    <span>${rating ? `${rating}/5` : "Chưa xếp hạng"}</span>
  </div>`;
}

function spyPostDetailFooter(post, index = state.spyModalIndex) {
  const postUrl = safeFacebookPostUrl(post.url);
  const hasPrevious = Number(index) > 0;
  const hasNext = Number(index) >= 0 && Number(index) < state.spyPosts.length - 1;
  return `<div class="spy-modal-navigation">
      <button class="btn btn-secondary" onclick="navigateSpyModal(-1)" ${hasPrevious ? "" : "disabled"} title="Bài trước (←)">← Trước</button>
      <span>${Number(index) + 1}/${state.spyPosts.length}</span>
      <button class="btn btn-secondary" onclick="navigateSpyModal(1)" ${hasNext ? "" : "disabled"} title="Bài kế tiếp (→)">Sau →</button>
    </div>
    ${spyPostRatingMarkup(post)}
    <button class="btn btn-danger" onclick="deleteCurrentSpyPost()" ${state.spyModalDeleting ? "disabled" : ""} title="Xóa bài và media (Delete)">🗑 Xóa</button>
    ${postUrl ? `<a class="btn btn-teal" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener">Mở bài Facebook</a>` : ""}
    <button class="btn btn-secondary" onclick="closeModal()">Đóng</button>`;
}

function previewSpyPostMarkup(post, source) {
  const isVideoPost = post.post_type === "Video";
  const postUrl = safeFacebookPostUrl(post.url);
  const media = source
    ? `<div class="spy-media-lightbox spy-preview-lightbox">${source.kind === "video"
      ? `<video src="${escapeHtml(source.src)}" controls preload="metadata" playsinline autoplay data-spy-autoplay onerror="handleSpyVideoError(this, '${escapeHtml(postUrl)}')"></video>`
      : `<img src="${escapeHtml(source.src)}" alt="Thumbnail bài viết" referrerpolicy="no-referrer" onerror="this.parentElement.innerHTML='<div class=&quot;spy-preview-media-error&quot;>Không thể tải thumbnail.</div>'">`
    }${isVideoPost && source.kind !== "video" && postUrl ? `<a class="spy-preview-video-indicator" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener" title="Mở xem video trên Facebook"><span>▶</span> Mở video trên Facebook</a>` : (isVideoPost && source.kind !== "video" ? '<span class="spy-preview-video-indicator"><span>▶</span> Video</span>' : "")}</div>`
    : `<div class="spy-detail-empty-media spy-preview-empty-media">
        <div class="spy-preview-empty-icon">${isVideoPost ? "🎥" : (post.post_type === "Ảnh" ? "🖼️" : "📄")}</div>
        <strong>Bài này chưa có thumbnail xem trước</strong>
        <span>Hãy quét lại Fanpage hoặc tải media để tạo preview nội bộ.</span>
      </div>`;
  return `<article class="spy-post-detail">
    <div class="spy-detail-summary">
      <div class="spy-detail-meta-badges">
        <span class="badge badge-teal">${escapeHtml(post.page_name || "Fanpage")}</span>
        <span class="badge badge-gray">${escapeHtml(post.date || "Không rõ ngày")}</span>
        ${post.post_id ? `<span class="badge badge-blue spy-detail-id-badge" onclick="copySpyPostId('${escapeHtml(post.post_id)}')" title="Nhấp để sao chép ID: ${escapeHtml(post.post_id)}">ID: ${escapeHtml(post.post_id)} 📋</span>` : ""}
      </div>
      <div class="spy-detail-metrics">
        <span>👍 ${Number(post.engagement) || 0}</span><span>💬 ${Number(post.comments) || 0}</span>
        <span>🔁 ${Number(post.shares) || 0}</span>${isVideoPost || post.view_count ? `<span>👁 ${Number(post.view_count) || 0}</span>` : ""}
      </div>
    </div>
    <section>
      <h4 class="spy-detail-media-title">Thumbnail xem trước ${isVideoPost ? '<span class="spy-detail-video-label">Video</span>' : ""}</h4>
      ${media}
    </section>
    <section class="spy-detail-caption">
      <h4>Nội dung bài viết</h4>
      <div>${post.caption ? escapeHtml(post.caption) : "<i>(Không có nội dung văn bản)</i>"}</div>
    </section>
  </article>`;
}

function downloadedSpyPostMarkup(post) {
  const media = Array.isArray(post.media) ? post.media : [];
  const videoItems = media.filter(item => item.kind === "video");
  const imageItems = media.filter(item => item.kind !== "video");
  const isVideoPost = post.post_type === "Video";
  const postUrl = safeFacebookPostUrl(post.url);

  let mediaSectionHtml = "";

  if (isVideoPost) {
    if (videoItems.length > 0) {
      const primaryVideo = videoItems[0];
      const posterItem = imageItems[0];
      const posterAttr = posterItem ? `poster="${escapeHtml(posterItem.url)}"` : "";
      const remainingMedia = media.filter((_, idx) => idx !== media.indexOf(primaryVideo));

      mediaSectionHtml = `
        <div class="spy-detail-primary-video">
          <div class="spy-video-player-wrap">
            <video src="${escapeHtml(primaryVideo.url)}" controls preload="metadata" playsinline autoplay data-spy-autoplay ${posterAttr} onerror="handleSpyVideoError(this, '${escapeHtml(postUrl)}')">
              Trình duyệt không hỗ trợ phát video này.
            </video>
          </div>
          <div class="spy-video-caption-bar">
            <span class="badge badge-teal">🎬 Video đã tải</span>
            <span>${escapeHtml(primaryVideo.name || "video_001.mp4")}</span>
          </div>
        </div>
        ${remainingMedia.length ? `
          <h4 class="spy-detail-media-title" style="margin-top:14px;">Media bổ sung <span>${remainingMedia.length}</span></h4>
          <div class="spy-detail-gallery">
            ${remainingMedia.map(item => `
              <figure class="spy-detail-media">
                ${item.kind === "video"
                  ? `<video src="${escapeHtml(item.url)}" controls preload="metadata" playsinline></video>`
                  : `<img src="${escapeHtml(item.url)}" loading="lazy" alt="${escapeHtml(item.name || "Media bài viết")}">`}
                <figcaption>${escapeHtml(item.name || "Media")}</figcaption>
              </figure>
            `).join("")}
          </div>
        ` : ""}
      `;
    } else {
      const thumbUrl = imageItems.length > 0 ? imageItems[0].url : (post.media_preview_url || "");
      mediaSectionHtml = `
        <div class="spy-video-missing-banner">
          <div class="spy-video-missing-header">
            <span class="spy-video-missing-icon">⚠️</span>
            <div>
              <div class="spy-video-missing-title">Bài viết Video này chưa có file video trên máy</div>
              <div class="spy-video-missing-desc">
                ${post.download_error ? escapeHtml(post.download_error) : "File video chưa tải được về máy (hiện tại chỉ có ảnh thumbnail và nội dung caption)."}
              </div>
            </div>
          </div>
          <div class="spy-video-missing-actions">
            ${postUrl ? `<a class="btn btn-teal btn-sm" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener">▶ Xem video trực tiếp trên Facebook</a>` : ""}
            ${postUrl ? `<button type="button" class="btn btn-primary btn-sm" onclick="sendPostToDownloader('${escapeHtml(postUrl)}')">⬇ Tải video bài này</button>` : ""}
          </div>
        </div>
        ${thumbUrl ? `
          <div class="spy-media-lightbox spy-preview-lightbox" style="margin-top:12px; position:relative;">
            <img src="${escapeHtml(thumbUrl)}" alt="Thumbnail video">
            ${postUrl ? `<a class="spy-preview-video-indicator" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener" title="Mở xem video trên Facebook"><span>▶</span> Mở video trên Facebook</a>` : ""}
          </div>
        ` : ""}
      `;
    }
  } else {
    const firstVideoIndex = media.findIndex(item => item.kind === "video");
    const gallery = media.length
      ? `<div class="spy-detail-gallery ${media.length === 1 ? "spy-detail-gallery-single" : ""}">${media.map((item, mediaIndex) => `
          <figure class="spy-detail-media">
            ${item.kind === "video"
              ? `<video src="${escapeHtml(item.url)}" controls preload="metadata" playsinline ${mediaIndex === firstVideoIndex ? "autoplay data-spy-autoplay" : ""}></video>`
              : `<img src="${escapeHtml(item.url)}" loading="lazy" alt="${escapeHtml(item.name || "Media bài viết")}">`}
            ${media.length > 1 ? `<figcaption>${escapeHtml(item.name || `Media ${Number(item.index) + 1}`)}</figcaption>` : ""}
          </figure>`).join("")}</div>`
      : `<div class="spy-detail-empty-media">📭 Không tìm thấy file media trong thư mục đã tải.</div>`;

    mediaSectionHtml = gallery;
  }

  return `<article class="spy-post-detail">
    <div class="spy-detail-summary">
      <div class="spy-detail-meta-badges">
        <span class="badge badge-teal">${escapeHtml(post.page_name || "Fanpage")}</span>
        <span class="badge badge-gray">${escapeHtml(post.date || "Không rõ ngày")}</span>
        ${post.post_id ? `<span class="badge badge-blue spy-detail-id-badge" onclick="copySpyPostId('${escapeHtml(post.post_id)}')" title="Nhấp để sao chép ID: ${escapeHtml(post.post_id)}">ID: ${escapeHtml(post.post_id)} 📋</span>` : ""}
      </div>
      <div class="spy-detail-metrics">
        <span>👍 ${Number(post.engagement) || 0}</span><span>💬 ${Number(post.comments) || 0}</span>
        <span>🔁 ${Number(post.shares) || 0}</span>${post.post_type === "Video" || post.view_count ? `<span>👁 ${Number(post.view_count) || 0}</span>` : ""}
      </div>
    </div>
    <section class="spy-detail-caption">
      <h4>Nội dung bài viết</h4>
      <div>${post.caption ? escapeHtml(post.caption) : "<i>(Không có nội dung văn bản)</i>"}</div>
    </section>
    <section>
      <h4 class="spy-detail-media-title">Media đã tải <span>${media.length}</span></h4>
      ${mediaSectionHtml}
    </section>
  </article>`;
}

async function openSpyMedia(index) {
  const post = state.spyPosts[index];
  if (!post) return;
  state.spyModalDeleting = false;
  const requestId = ++state.spyModalRequest;
  state.spyModalIndex = index;
  if (post.downloaded) {
    openModal(`Bài đã tải · ${post.page_name || "Facebook"}`, `<div class="spy-detail-loading">Đang tải đầy đủ nội dung và media…</div>`, spyPostDetailFooter(post, index), { spyIndex: index });
    try {
      const response = await fetch(`/api/spy/posts/${Number(post.id)}/detail`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Không thể đọc bài đã tải");
      if (requestId !== state.spyModalRequest || state.spyModalIndex !== index) return;
      document.getElementById("modal-body").innerHTML = downloadedSpyPostMarkup(result.data);
      document.getElementById("modal-footer").innerHTML = spyPostDetailFooter(result.data, index);
      playSpyModalVideo();
    } catch (error) {
      if (requestId !== state.spyModalRequest || state.spyModalIndex !== index) return;
      document.getElementById("modal-body").innerHTML = `<div class="spy-detail-error">${escapeHtml(error.message || "Không thể tải nội dung bài viết.")}</div>`;
    }
    return;
  }
  const source = spyMediaSource(post);
  const title = `Xem trước · ${post.page_name || "Bài viết Facebook"}`;
  const body = previewSpyPostMarkup(post, source);
  const footer = spyPostDetailFooter(post, index);
  openModal(title, body, footer, { spyIndex: index });
  playSpyModalVideo();
}

function handleSpyVideoError(videoEl, postUrl) {
  const container = videoEl.closest(".spy-video-player-wrap") || videoEl.parentElement;
  if (!container) return;
  container.innerHTML = `<div class="spy-preview-media-error" style="padding:24px;text-align:center;">
    <div style="font-size:14px;font-weight:600;margin-bottom:8px;color:#f87171;">⚠️ Không thể phát video trực tiếp trong popup</div>
    <div style="font-size:12px;color:rgba(255,255,255,.8);margin-bottom:12px;">Trình duyệt không hỗ trợ định dạng này hoặc file video chưa hoàn tất.</div>
    ${postUrl ? `<a class="btn btn-teal btn-sm" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener">▶ Mở xem trực tiếp trên Facebook</a>` : ""}
  </div>`;
}

function sendPostToDownloader(url) {
  if (!url) return;
  closeModal();
  const tabItem = document.querySelector('.nav-item[data-tab="tab-downloader"]');
  if (tabItem) tabItem.click();
  const textarea = document.getElementById("dl-urls");
  if (textarea) {
    textarea.value = url;
    textarea.focus();
    showToast("Đã đưa link bài viết vào tab Tải Facebook", "info");
  }
}

function copySpyPostId(postId) {
  if (!postId) return;
  const notify = () => showToast(`Đã sao chép ID bài viết: ${postId}`, "success");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(postId).then(notify).catch(() => {
      fallbackCopyText(postId);
      notify();
    });
  } else {
    fallbackCopyText(postId);
    notify();
  }
}

function fallbackCopyText(text) {
  const input = document.createElement("input");
  input.value = text;
  document.body.appendChild(input);
  input.select();
  try { document.execCommand("copy"); } catch (_) {}
  document.body.removeChild(input);
}

function playSpyModalVideo() {
  const video = document.querySelector("#generic-modal.active video[data-spy-autoplay]");
  if (!video) return;
  video.muted = false;
  video.defaultMuted = false;
  if (video.volume === 0) video.volume = 1;
  const playAttempt = video.play();
  if (playAttempt?.catch) playAttempt.catch(() => {});
}

function navigateSpyModal(offset) {
  if (state.spyModalIndex === null || state.spyModalDeleting) return;
  const target = state.spyModalIndex + Number(offset);
  if (target < 0 || target >= state.spyPosts.length) return;
  openSpyMedia(target);
}

async function rateCurrentSpyPost(rating) {
  const index = state.spyModalIndex;
  const post = index === null ? null : state.spyPosts[index];
  if (!post) return;
  try {
    const response = await fetch(`/api/spy/posts/${Number(post.id)}/rating`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: Number(rating) })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể lưu xếp hạng");
    post.rating = Number(rating);
    document.getElementById("modal-footer").innerHTML = spyPostDetailFooter(post, index);
    showToast(`Đã xếp hạng ${rating} sao`, "success");
  } catch (error) {
    showToast(error.message || "Lỗi kết nối khi lưu xếp hạng", "error");
  }
}

async function deleteCurrentSpyPost() {
  const index = state.spyModalIndex;
  const post = index === null ? null : state.spyPosts[index];
  if (!post || state.spyModalDeleting) return;
  const nextPost = state.spyPosts[index + 1] || state.spyPosts[index - 1] || null;
  const nextPostId = nextPost ? Number(nextPost.id) : null;
  const currentPostId = Number(post.id);
  const modalRequest = state.spyModalRequest;
  state.spyModalDeleting = true;
  document.getElementById("modal-body").innerHTML = `<div class="spy-detail-loading">Đang xóa bài viết và media đã tải…</div>`;
  document.getElementById("modal-footer").innerHTML = spyPostDetailFooter(post, index);
  const deleted = await deleteSpyPosts([currentPostId], { deleteMedia: true, requireConfirmation: false });
  if (state.spyModalRequest !== modalRequest || !document.getElementById("generic-modal").classList.contains("active")) return;
  state.spyModalDeleting = false;
  if (!deleted) {
    const currentIndex = state.spyPosts.findIndex(item => Number(item.id) === currentPostId);
    if (currentIndex >= 0) openSpyMedia(currentIndex);
    else closeModal();
    return;
  }
  if (!state.spyPosts.length) {
    closeModal();
    return;
  }
  const nextIndex = nextPostId === null
    ? Math.min(index, state.spyPosts.length - 1)
    : state.spyPosts.findIndex(item => Number(item.id) === nextPostId);
  openSpyMedia(nextIndex >= 0 ? nextIndex : Math.min(index, state.spyPosts.length - 1));
}

function renderSpyPostsGrid() {
  const container = document.getElementById("spy-posts-grid");
  container.innerHTML = "";

  if (!state.spyPosts.length) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px;" class="text-muted">Không tìm thấy bài viết phù hợp</div>`;
    return;
  }

  const fragment = document.createDocumentFragment();
  state.spyPosts.forEach((post, index) => {
    const card = document.createElement("div");
    card.className = "post-card";
    card.dataset.postRowId = Number(post.id);

    card.innerHTML = `
      <label class="spy-card-selector" title="Chọn bài này">
        <input class="spy-post-select" type="checkbox" data-post-row-id="${Number(post.id)}" onchange="toggleSpyPostSelection(${Number(post.id)}, this.checked)">
        <span>Chọn</span>
      </label>
      <div class="post-card-thumb">
        ${spyMediaPreviewMarkup(post, index, "grid")}
      </div>
      <div class="post-card-body">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span class="badge badge-teal">${escapeHtml(post.page_name)}</span>
          <span>${spyRatingListMarkup(post)} <span class="badge badge-gray">${escapeHtml(post.date || 'Hôm nay')}</span></span>
        </div>
        <div class="post-card-caption" title="${escapeHtml(post.caption || "")}">${post.caption ? escapeHtml(post.caption) : '<i>(Không có nội dung văn bản)</i>'}</div>
        <div class="post-card-meta">
          <span>👍 ${post.engagement || 0} | 💬 ${post.comments || 0} | 🔁 ${post.shares || 0}${post.post_type === 'Video' || post.view_count ? ` | 👁 ${post.view_count || '—'}` : ''}</span>
          <span class="spy-status-slot">${spyDownloadStatusMarkup(post)}</span>
        </div>
        <div class="spy-post-actions">
          <button class="btn btn-teal btn-sm" onclick="downloadSpyPost(${Number(post.id)})" ${post.url ? "" : "disabled"}>⬇ Download</button>
          <button class="btn btn-danger btn-sm" onclick="deleteSpyPost(${Number(post.id)})">🗑 Xóa</button>
        </div>
      </div>
    `;
    fragment.appendChild(card);
  });
  container.appendChild(fragment);
  observeSpyLazyMedia();
}

function renderSpyPostsTable() {
  const tbody = document.getElementById("spy-posts-tbody");
  tbody.innerHTML = "";

  const fragment = document.createDocumentFragment();
  state.spyPosts.forEach((post, i) => {
    const totalEngagement = (Number(post.engagement) || 0) + (Number(post.comments) || 0) + (Number(post.shares) || 0);
    const tr = document.createElement("tr");
    tr.dataset.postRowId = Number(post.id);
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    tr.innerHTML = `
      <td style="padding: 10px 12px;"><input class="spy-post-select" type="checkbox" data-post-row-id="${Number(post.id)}" aria-label="Chọn bài ${i + 1}" onchange="toggleSpyPostSelection(${Number(post.id)}, this.checked)"></td>
      <td style="padding: 10px 12px;">${i + 1}</td>
      <td style="padding: 7px 10px;">${spyMediaPreviewMarkup(post, i, "table")}</td>
      <td style="padding: 10px 12px; font-weight: 600;">${escapeHtml(post.page_name)}</td>
      <td style="padding: 10px 12px;">${escapeHtml(post.date || '—')}</td>
      <td style="padding: 10px 12px;"><span class="badge badge-teal">${escapeHtml(post.post_type)}</span></td>
      <td style="padding: 10px 12px; font-weight: 700;">${post.engagement || 0}</td>
      <td style="padding: 10px 12px; font-weight: 700;">${post.comments || 0}</td>
      <td style="padding: 10px 12px; font-weight: 700;">${post.shares || 0}</td>
      <td style="padding: 10px 12px; font-weight: 700;">${post.post_type === 'Video' || post.view_count ? (post.view_count || '—') : '—'}</td>
      <td style="padding: 10px 12px; font-weight: 800;">${totalEngagement}</td>
      <td style="padding: 10px 12px;"><div class="spy-caption-clamp" title="${escapeHtml(post.caption || "")}">${escapeHtml(post.caption || '—')}</div></td>
      <td style="padding: 10px 12px;"><span class="spy-status-slot">${spyDownloadStatusMarkup(post)}</span> ${spyRatingListMarkup(post)}</td>
      <td style="padding: 10px 12px;"><div class="spy-post-actions"><button class="btn btn-teal btn-sm" onclick="downloadSpyPost(${Number(post.id)})" ${post.url ? "" : "disabled"}>Download</button><button class="btn btn-danger btn-sm" onclick="deleteSpyPost(${Number(post.id)})">Xóa</button></div></td>
    `;
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
  updateSortIndicators("spy", state.spySort);
  observeSpyLazyMedia();
}

function renderSpyPosts() {
  const grid = document.getElementById("spy-posts-grid");
  const tableWrap = document.getElementById("spy-posts-table-wrap");
  const tbody = document.getElementById("spy-posts-tbody");
  if (state.spyView === "table") {
    grid.innerHTML = "";
    grid.style.display = "none";
    tableWrap.style.display = "block";
    renderSpyPostsTable();
    return;
  }
  tbody.innerHTML = "";
  tableWrap.style.display = "none";
  grid.style.display = "grid";
  renderSpyPostsGrid();
}

function setSpyView(view) {
  if (state.spyView === view) return;
  state.spyView = view;
  renderSpyPosts();
}

function getSpyPost(rowId) {
  return state.spyPosts.find(post => Number(post.id) === Number(rowId));
}

function spyDownloadStatusMarkup(post) {
  const status = post.download_status || (post.downloaded ? "downloaded" : "not_downloaded");
  const states = {
    not_downloaded: { label: "Chưa tải", badge: "badge-amber", icon: "○" },
    downloading: { label: "Đang tải", badge: "badge-teal", icon: "↻" },
    failed: { label: "Tải lỗi", badge: "badge-red", icon: "!" },
    thumbnail_only: { label: "Thiếu video", badge: "badge-amber", icon: "⚠" },
    downloaded: { label: "Đã tải", badge: "badge-green", icon: "✓" }
  };
  const item = states[status] || states.not_downloaded;
  const error = ["failed", "thumbnail_only"].includes(status) && post.download_error
    ? ` title="${escapeHtml(post.download_error)}"`
    : "";
  return `<span class="badge ${item.badge}"${error}>${item.icon} ${item.label}</span>`;
}

function updateSpyPostStatusUi(post) {
  const rowId = Number(post.id);
  const statusMarkup = spyDownloadStatusMarkup(post);
  const card = document.querySelector(`.post-card[data-post-row-id="${rowId}"]`);
  if (card) {
    const slot = card.querySelector(".spy-status-slot");
    if (slot) slot.innerHTML = statusMarkup;
  }
  const row = document.querySelector(`tr[data-post-row-id="${rowId}"]`);
  if (row) {
    const slot = row.querySelector(".spy-status-slot");
    if (slot) slot.innerHTML = statusMarkup;
  }
}

function spyRatingListMarkup(post) {
  const rating = Math.max(0, Math.min(5, Number(post.rating) || 0));
  return rating ? `<span class="spy-list-rating" title="Đã xếp hạng ${rating}/5 sao">★ ${rating}</span>` : "";
}

function getSelectedSpyPosts() {
  return state.spyPosts.filter(post => state.selectedSpyPostIds.has(Number(post.id)));
}

function syncSpyPostSelectionUi() {
  document.querySelectorAll(".spy-post-select").forEach(input => {
    const selected = state.selectedSpyPostIds.has(Number(input.dataset.postRowId));
    input.checked = selected;
    input.closest(".post-card")?.classList.toggle("spy-post-selected", selected);
    input.closest("tr")?.classList.toggle("spy-table-selected", selected);
  });
  const count = state.selectedSpyPostIds.size;
  const total = state.spyPosts.length;
  const selectAll = document.getElementById("spy-select-all-posts");
  if (selectAll) {
    selectAll.checked = total > 0 && count === total;
    selectAll.indeterminate = count > 0 && count < total;
    selectAll.disabled = total === 0;
  }
  const counter = document.getElementById("spy-selected-counter");
  if (counter) counter.textContent = `${count} bài đã chọn`;
  ["btn-download-spy-posts", "btn-delete-spy-posts"].forEach(id => {
    const button = document.getElementById(id);
    if (button) button.disabled = count === 0;
  });
  const retryButton = document.getElementById("btn-retry-spy-posts");
  if (retryButton) {
    const retryableCount = getSelectedSpyPosts().filter(post => ["failed", "thumbnail_only"].includes(post.download_status)).length;
    retryButton.disabled = retryableCount === 0;
  }
}

function toggleSpyPostSelection(rowId, checked) {
  const normalizedId = Number(rowId);
  if (checked) state.selectedSpyPostIds.add(normalizedId);
  else state.selectedSpyPostIds.delete(normalizedId);
  syncSpyPostSelectionUi();
}

function selectAllSpyPosts(checked) {
  state.selectedSpyPostIds.clear();
  if (checked) state.spyPosts.forEach(post => state.selectedSpyPostIds.add(Number(post.id)));
  syncSpyPostSelectionUi();
}

async function startSpyPostDownloads(posts) {
  const downloads = [];
  const seenPostIds = new Set();
  posts.forEach(post => {
    const url = safeFacebookPostUrl(post.url);
    const rowId = Number(post.id) || 0;
    if (!url || !rowId || seenPostIds.has(rowId)) return;
    seenPostIds.add(rowId);
    downloads.push({ url, rowId });
  });
  const urls = downloads.map(item => item.url);
  if (!urls.length) {
    showToast("Bài đã chọn không có link Facebook hợp lệ", "warning");
    return;
  }
  const urlsText = urls.join("\n");
  if (urlsText.length > 450000) {
    showToast("Danh sách quá lớn. Hãy chọn ít bài hơn cho mỗi lượt tải", "warning");
    return;
  }
  try {
    const response = await fetch("/api/download/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls: urlsText,
        max_threads: parseInt(document.getElementById("dl-threads")?.value) || 3,
        use_accounts: Boolean(document.getElementById("dl-use-accounts")?.checked),
        account_ids: selectedDownloadAccountIds(),
        source_post_row_ids: downloads.map(item => item.rowId)
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể bắt đầu tải");
    const startedPostIds = new Set(downloads.map(item => item.rowId));
    state.spyPosts.forEach(post => {
      if (startedPostIds.has(Number(post.id))) {
        post.download_status = "downloading";
        post.download_error = "";
        post.downloaded = 0;
        updateSpyPostStatusUi(post);
      }
    });
    syncSpyPostSelectionUi();
    showToast(`Đã bắt đầu Download ${downloads.length} bài`, "success");
  } catch (error) {
    showToast(error.message || "Lỗi kết nối khi tải bài", "error");
  }
}

function downloadSpyPost(rowId) {
  const post = getSpyPost(rowId);
  if (post) startSpyPostDownloads([post]);
}

function downloadSelectedSpyPosts() {
  startSpyPostDownloads(getSelectedSpyPosts());
}

async function retrySelectedSpyPosts() {
  const postRowIds = [...state.selectedSpyPostIds].map(Number).filter(Boolean);
  if (!postRowIds.length) return;
  try {
    const response = await fetch("/api/spy/posts/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        post_row_ids: postRowIds,
        max_threads: parseInt(document.getElementById("dl-threads")?.value) || 3,
        use_accounts: Boolean(document.getElementById("dl-use-accounts")?.checked),
        account_ids: selectedDownloadAccountIds()
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể thử lại bài đã chọn");
    state.spyPosts.forEach(post => {
      if (postRowIds.includes(Number(post.id)) && ["failed", "thumbnail_only"].includes(post.download_status)) {
        post.download_status = "downloading";
        post.download_error = "";
        post.downloaded = 0;
        updateSpyPostStatusUi(post);
      }
    });
    syncSpyPostSelectionUi();
    showToast(`Đã thử lại ${Number(result.retrying) || 0} bài${result.skipped ? `; bỏ qua ${result.skipped} bài không phù hợp` : ""}`, "success");
  } catch (error) {
    showToast(error.message || "Lỗi kết nối khi thử lại bài", "error");
  }
}

async function deleteSpyPosts(rowIds, { deleteMedia = true, requireConfirmation = false } = {}) {
  const uniqueIds = [...new Set(rowIds.map(Number).filter(value => value > 0))];
  if (!uniqueIds.length) {
    showToast("Chưa chọn bài cần xóa", "warning");
    return false;
  }
  if (requireConfirmation && !confirm(`Xóa ${uniqueIds.length} bài khỏi Kho Bài Viết?`)) return false;
  try {
    const response = await fetch("/api/spy/posts/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_row_ids: uniqueIds, delete_media: deleteMedia })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể xóa bài");
    const deleted = Number(result.data?.deleted) || 0;
    const mediaDeleted = Number(result.data?.media_deleted) || 0;
    const mediaFailed = (Number(result.data?.media_failed) || 0) + (Number(result.data?.media_skipped) || 0);
    showToast(
      deleteMedia
        ? (mediaFailed ? `Đã xóa ${deleted} bài; ${mediaFailed} file media không thể xóa` : (mediaDeleted > 0 ? `Đã xóa ${deleted} bài và ${mediaDeleted} file media liên quan` : `Đã xóa ${deleted} bài`))
        : `Đã xóa ${deleted} bài; media vẫn được giữ`,
      mediaFailed ? "warning" : "success"
    );
    uniqueIds.forEach(id => state.selectedSpyPostIds.delete(id));
    await loadSpyPages();
    await fetchStats();
    return true;
  } catch (error) {
    showToast(error.message || "Lỗi kết nối khi xóa bài", "error");
    return false;
  }
}

function deleteSpyPost(rowId) {
  deleteSpyPosts([rowId], { deleteMedia: true, requireConfirmation: false });
}

function deleteSelectedSpyPosts() {
  deleteSpyPosts([...state.selectedSpyPostIds], { deleteMedia: true, requireConfirmation: false });
}

// ─── Tab 4: Accounts Manager (Master-Detail Split View) ─────────────────────

async function loadAccounts() {
  try {
    const res = await fetch("/api/accounts/");
    const json = await res.json();
    if (json.status === "success") {
      state.accounts = json.data;
      refreshDownloadAccountOptions();
      loadScrapeAccounts();
      const currentAccountIds = new Set(state.accounts.map(account => Number(account.id)));
      state.selectedAccountIds = new Set(
        [...state.selectedAccountIds].filter(accountId => currentAccountIds.has(Number(accountId)))
      );
      updateAccountsToolbarState();
      renderAccountsList();

      const currentSelectedExists = state.accounts.some(a => Number(a.id) === Number(state.selectedAccountId));
      if (!currentSelectedExists && state.selectedAccountId !== "new") {
        if (state.accounts.length > 0) {
          selectAccount(state.accounts[0].id);
        } else {
          state.selectedAccountId = null;
          renderDetailEmptyState();
        }
      } else if (currentSelectedExists) {
        loadAccountDetail(state.selectedAccountId);
      }
    }
  } catch (e) {}
}

function updateAccountsToolbarState() {
  const exportButton = document.getElementById("btn-export-profile");
  if (exportButton) exportButton.disabled = state.accounts.length === 0;
  const cleanupButton = document.getElementById("btn-cleanup-profiles");
  if (cleanupButton) cleanupButton.disabled = state.accounts.length === 0;

  const countAllEl = document.getElementById("count-pill-all");
  if (countAllEl) countAllEl.textContent = state.accounts.length;
  const countFbEl = document.getElementById("count-pill-fb");
  if (countFbEl) countFbEl.textContent = state.accounts.length;
  const countActiveEl = document.getElementById("count-pill-active");
  if (countActiveEl) countActiveEl.textContent = state.accounts.filter(a => a.is_active).length;

  updateSelectedAccountsPreflightControl();
}

function updateSelectedAccountsPreflightControl() {
  const button = document.getElementById("btn-preflight-selected-accounts");
  if (!button) return;

  const selectedCount = state.selectedAccountIds.size;
  button.disabled = selectedCount === 0 || state.selectedAccountsPreflightRunning;
  button.textContent = state.selectedAccountsPreflightRunning
    ? `Đang kiểm tra 0/${selectedCount}...`
    : `✓ Check Preflight (${selectedCount})`;
}

function getAccountStatusPresentation(account) {
  if (!account.is_active) {
    return { className: "disabled", text: "Đã tắt", title: "Account đang tắt." };
  }

  const code = String(account.preflight_status || "").trim();
  const message = String(account.preflight_message || "").trim();
  const checkedAt = String(account.preflight_checked_at || "").trim();
  const detail = [code, message, checkedAt ? `Kiểm tra: ${checkedAt}` : ""]
    .filter(Boolean)
    .join(" · ");
  if (code === "READY") {
    return { className: "ready", text: "Sẵn sàng", title: detail || "Phiên Facebook hợp lệ." };
  }
  if (["AUTH_EXPIRED", "AUTH_REQUIRED"].includes(code)) {
    return { className: "session-expired", text: "Mất phiên", title: detail || "Cần đăng nhập lại Facebook." };
  }
  if (code) {
    return { className: "preflight-failed", text: "Cần kiểm tra", title: detail || "Preflight chưa thành công." };
  }
  return { className: "enabled", text: "Đang bật", title: "Account đang bật; chưa check phiên Facebook." };
}

function applyAccountPreflightResult(accountId, result) {
  const account = state.accounts.find(item => Number(item.id) === Number(accountId));
  if (!account) return;
  account.preflight_status = result.code || "PREFLIGHT_FAILED";
  account.preflight_message = result.message || "Không thể kiểm tra phiên Facebook.";
  account.preflight_checked_at = result.checked_at || new Date().toLocaleString("vi-VN");
  renderAccountsList();
}

function updateAccountListSelectionControls(filtered = getFilteredAndSortedAccounts()) {
  const visibleAccountIds = filtered.map(account => Number(account.id));
  const favoriteAccountIds = filtered
    .filter(account => state.accountFavorites.has(Number(account.id)))
    .map(account => Number(account.id));
  const hasAllSelected = visibleAccountIds.length > 0
    && visibleAccountIds.every(accountId => state.selectedAccountIds.has(accountId));
  const hasAllFavoritesSelected = favoriteAccountIds.length > 0
    && favoriteAccountIds.every(accountId => state.selectedAccountIds.has(accountId));

  const selectAllButton = document.getElementById("btn-toggle-select-all-accounts");
  if (selectAllButton) {
    selectAllButton.disabled = visibleAccountIds.length === 0 || state.selectedAccountsPreflightRunning;
    selectAllButton.textContent = hasAllSelected ? "☑" : "☐";
    selectAllButton.title = hasAllSelected
      ? "Bỏ chọn tất cả account đang hiển thị"
      : "Chọn tất cả account đang hiển thị";
    selectAllButton.setAttribute("aria-label", selectAllButton.title);
    selectAllButton.setAttribute("aria-pressed", String(hasAllSelected));
    selectAllButton.classList.toggle("active", hasAllSelected);
  }

  const selectFavoritesButton = document.getElementById("btn-toggle-select-favorite-accounts");
  if (selectFavoritesButton) {
    selectFavoritesButton.disabled = favoriteAccountIds.length === 0 || state.selectedAccountsPreflightRunning;
    selectFavoritesButton.textContent = hasAllFavoritesSelected ? "★" : "☆";
    selectFavoritesButton.title = hasAllFavoritesSelected
      ? `Bỏ chọn ${favoriteAccountIds.length} account yêu thích đang hiển thị`
      : `Chọn ${favoriteAccountIds.length} account yêu thích đang hiển thị`;
    selectFavoritesButton.setAttribute("aria-label", selectFavoritesButton.title);
    selectFavoritesButton.setAttribute("aria-pressed", String(hasAllFavoritesSelected));
    selectFavoritesButton.classList.toggle("active", hasAllFavoritesSelected);
  }
}

function toggleAccountPreflightSelectionFor(accountIds) {
  const normalizedIds = [...new Set(accountIds.map(Number))];
  if (!normalizedIds.length || state.selectedAccountsPreflightRunning) return;

  const hasAllSelected = normalizedIds.every(accountId => state.selectedAccountIds.has(accountId));
  normalizedIds.forEach(accountId => {
    if (hasAllSelected) {
      state.selectedAccountIds.delete(accountId);
    } else {
      state.selectedAccountIds.add(accountId);
    }
  });
  renderAccountsList();
  updateSelectedAccountsPreflightControl();
}

function toggleAllVisibleAccountPreflightSelection() {
  toggleAccountPreflightSelectionFor(getFilteredAndSortedAccounts().map(account => account.id));
}

function toggleVisibleFavoriteAccountPreflightSelection() {
  const favoriteIds = getFilteredAndSortedAccounts()
    .filter(account => state.accountFavorites.has(Number(account.id)))
    .map(account => account.id);
  toggleAccountPreflightSelectionFor(favoriteIds);
}

function getFilteredAndSortedAccounts() {
  let list = [...state.accounts];

  // Tab filter
  if (state.accountTabFilter === "facebook") {
    list = list.filter(a => (a.platform || "facebook").toLowerCase() === "facebook");
  } else if (state.accountTabFilter === "active") {
    list = list.filter(a => a.is_active);
  }

  // Status dropdown filter
  if (state.accountStatusFilter === "active") {
    list = list.filter(a => a.is_active);
  } else if (state.accountStatusFilter === "disabled") {
    list = list.filter(a => !a.is_active);
  } else if (state.accountStatusFilter === "has_cookie") {
    list = list.filter(a => a.has_cookie);
  } else if (state.accountStatusFilter === "no_cookie") {
    list = list.filter(a => !a.has_cookie);
  }

  // Search input
  const query = (state.accountSearchQuery || "").trim().toLowerCase();
  if (query) {
    list = list.filter(a => {
      const name = (a.label || "").toLowerCase();
      const user = (a.username || "").toLowerCase();
      const email = (a.email || "").toLowerCase();
      const id = String(a.id || "");
      return name.includes(query) || user.includes(query) || email.includes(query) || id === query;
    });
  }

  // Sort
  list.sort((a, b) => {
    if (state.accountSort === "name_asc") {
      const nameA = (a.label || a.username || "").toLowerCase();
      const nameB = (b.label || b.username || "").toLowerCase();
      return nameA.localeCompare(nameB, "vi");
    } else if (state.accountSort === "name_desc") {
      const nameA = (a.label || a.username || "").toLowerCase();
      const nameB = (b.label || b.username || "").toLowerCase();
      return nameB.localeCompare(nameA, "vi");
    } else if (state.accountSort === "id_asc") {
      return (Number(a.id) || 0) - (Number(b.id) || 0);
    } else if (state.accountSort === "id_desc") {
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    } else if (state.accountSort === "newest") {
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    }
    return 0;
  });

  return list;
}

function renderAccountsList() {
  const container = document.getElementById("account-cards-list");
  if (!container) return;

  const countBadge = document.getElementById("account-count-badge");
  const filtered = getFilteredAndSortedAccounts();

  if (countBadge) {
    countBadge.textContent = `Hiển thị ${filtered.length}/${state.accounts.length}`;
  }
  updateAccountListSelectionControls(filtered);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); padding: 40px 10px; font-size: 13px;">
        Không tìm thấy tài khoản phù hợp.
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  filtered.forEach((acc, index) => {
    const isSelected = Number(acc.id) === Number(state.selectedAccountId);
    const isPreflightSelected = state.selectedAccountIds.has(Number(acc.id));
    const isFav = state.accountFavorites.has(Number(acc.id));
    const card = document.createElement("div");
    card.className = `account-card ${isSelected ? "selected" : ""}`;
    card.dataset.accId = acc.id;
    card.onclick = () => selectAccount(acc.id);

    const displayName = escapeHtml(acc.label || acc.username || `Account #${acc.id}`);
    const displaySub = escapeHtml(acc.email || acc.username || "—");
    const status = getAccountStatusPresentation(acc);

    card.innerHTML = `
      <div class="card-left">
        <input type="checkbox" class="card-checkbox" ${isPreflightSelected ? "checked" : ""} onclick="event.stopPropagation()" onchange="toggleAccountPreflightSelection(event, ${acc.id})" title="Chọn để check preflight">
        <button type="button" class="card-star ${isFav ? "active" : ""}" onclick="toggleAccountFavorite(event, ${acc.id})" title="${isFav ? "Bỏ yêu thích" : "Đánh dấu yêu thích"}">★</button>
        <span class="card-index" title="Thứ tự">${index + 1}</span>
        <div class="card-info">
          <div class="card-title" title="${displayName}">${displayName}</div>
          <div class="card-meta-row">
            <span class="card-platform-pill">Facebook</span>
            <span class="card-email-text" title="${displaySub}">${displaySub}</span>
          </div>
        </div>
      </div>
      <div class="card-right">
        <button type="button" class="card-btn-preflight" onclick="event.stopPropagation(); checkAccountPreflight(${acc.id}, this)" title="Kiểm tra Chrome và phiên Facebook">✓ Check Preflight</button>
        <span class="card-status-badge ${status.className}" title="${escapeHtml(status.title)}">${escapeHtml(status.text)}</span>
        <button type="button" class="card-btn-delete" onclick="event.stopPropagation(); deleteAccount(${acc.id})" title="Xóa tài khoản">🗑 Xóa</button>
        <button type="button" class="card-btn-chrome" onclick="event.stopPropagation(); launchAccountChrome(${acc.id})" title="Mở Chrome Profile">🌐 Mở Chrome</button>
      </div>
    `;

    container.appendChild(card);
  });
}

function toggleAccountPreflightSelection(event, accId) {
  event.stopPropagation();
  const accountId = Number(accId);
  if (event.target.checked) {
    state.selectedAccountIds.add(accountId);
  } else {
    state.selectedAccountIds.delete(accountId);
  }
  updateSelectedAccountsPreflightControl();
  updateAccountListSelectionControls();
}

async function checkSelectedAccountsPreflight() {
  const selectedIds = [...state.selectedAccountIds]
    .map(Number)
    .filter(accountId => state.accounts.some(account => Number(account.id) === accountId));
  if (!selectedIds.length) {
    showToast("Vui lòng chọn ít nhất một account để check preflight.", "warning");
    updateSelectedAccountsPreflightControl();
    return;
  }

  const button = document.getElementById("btn-preflight-selected-accounts");
  state.selectedAccountsPreflightRunning = true;
  updateSelectedAccountsPreflightControl();

  let readyCount = 0;
  const failedAccounts = [];
  try {
    for (let index = 0; index < selectedIds.length; index += 1) {
      const accountId = selectedIds[index];
      const account = state.accounts.find(item => Number(item.id) === accountId);
      if (button) button.textContent = `Đang kiểm tra ${index + 1}/${selectedIds.length}...`;

      try {
        const response = await fetch(`/api/accounts/${accountId}/preflight`, { method: "POST" });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "Không thể check preflight");

        const data = result.data || {};
        applyAccountPreflightResult(accountId, data);
        if (data.ready) {
          readyCount += 1;
        } else {
          failedAccounts.push(account?.label || account?.username || `Account #${accountId}`);
        }
      } catch (error) {
        failedAccounts.push(account?.label || account?.username || `Account #${accountId}`);
      }
    }

    const checkedCount = selectedIds.length;
    const message = failedAccounts.length
      ? `Preflight xong: ${readyCount}/${checkedCount} account sẵn sàng; ${failedAccounts.length} account cần xử lý.`
      : `Preflight xong: ${readyCount}/${checkedCount} account sẵn sàng.`;
    showToast(message, failedAccounts.length ? "warning" : "success");
  } finally {
    state.selectedAccountsPreflightRunning = false;
    updateSelectedAccountsPreflightControl();
  }
}

function selectAccount(accId) {
  state.selectedAccountId = Number(accId);

  const cards = document.querySelectorAll(".account-card");
  cards.forEach(card => {
    if (Number(card.dataset.accId) === Number(accId)) {
      card.classList.add("selected");
    } else {
      card.classList.remove("selected");
    }
  });

  loadAccountDetail(accId);
}

async function loadAccountDetail(accId) {
  const container = document.getElementById("account-detail-container");
  if (!container) return;

  const idNum = Number(accId);
  const localAcc = state.accounts.find(a => Number(a.id) === idNum);
  if (localAcc) {
    state.accountDetailData = { ...localAcc };
    renderAccountDetail(state.accountDetailData, false);
  }

  try {
    const res = await fetch(`/api/accounts/${idNum}/detail`);
    if (res.ok) {
      const json = await res.json();
      if (json.status === "success" && json.data) {
        state.accountDetailData = json.data;
        renderAccountDetail(json.data, false);
      }
    } else if (!localAcc) {
      const json = await res.json().catch(() => ({}));
      showToast(json.detail || "Không tìm thấy tài khoản", "error");
    }
  } catch (e) {
    if (!localAcc) {
      showToast("Lỗi kết nối khi tải chi tiết tài khoản", "error");
    }
  }
}

function renderAccountDetail(data, isNew = false) {
  const container = document.getElementById("account-detail-container");
  if (!container) return;

  const accId = isNew ? null : Number(data.id);
  const title = isNew ? "Thêm tài khoản mới" : (data.label || data.username || `Account #${accId}`);
  const port = data.port || (accId ? (9400 + (accId % 400)) : 9400);
  const workerText = isNew
    ? "tinix-03 · Auto Profile"
    : `tinix-03 · http://127.0.0.1:${port}`;
  const isRunning = Boolean(data.is_chrome_running);
  const statusBannerClass = isRunning ? "running" : "";
  const statusBannerText = isNew
    ? "Sẵn sàng tạo cấu hình tài khoản mới"
    : (isRunning
        ? `running · CDP port ${port} · Profile: ${data.profile_dir || "mặc định"}`
        : `stopped · health:unknown · chưa có maintenance activity`);

  const hasPassword = Boolean(data.has_password);
  const has2fa = Boolean(data.has_2fa);
  const hasCookie = Boolean(data.has_cookie);
  const hasRecoveryCodes = Boolean(data.has_recovery_codes);
  const passwordPlaceholder = hasPassword ? "Đã lưu - nhập để thay thế" : "Chưa lưu";
  const faPlaceholder = has2fa ? "Đã lưu" : "Chưa lưu";
  const cookiePlaceholder = hasCookie ? "Đã lưu cookie Facebook (nhập để thay thế)" : "c_user=...; xs=...";
  const recoveryCodesPlaceholder = hasRecoveryCodes ? "Đã lưu mã khôi phục (nhập để thay thế)" : "Mỗi mã một dòng";

  container.innerHTML = `
    <!-- Detail Header -->
    <div class="detail-header">
      <div class="detail-title-group">
        <span class="account-title-bar">|</span>
        <span class="detail-account-name" id="detail-title-name">${escapeHtml(title)}</span>
        <span class="detail-badge-tag">${isNew ? "NEW" : "DETAILS"}</span>
        <span class="detail-meta-text">${escapeHtml(workerText)}</span>
      </div>
      <label class="custom-checkbox detail-enabled-toggle" title="Kích hoạt hoặc tạm ngưng tài khoản">
        <input type="checkbox" id="detail-input-active" ${data.is_active ?? true ? "checked" : ""} onchange="onAccountActiveToggle()">
        <span>Enabled</span>
      </label>
    </div>

    <!-- Status Banner -->
    <div class="detail-status-banner ${statusBannerClass}" id="detail-status-banner">
      <span class="status-dot"></span>
      <span id="detail-status-text">${escapeHtml(statusBannerText)}</span>
    </div>

    <!-- Form Row 1: Tên, Email, Recovery email -->
    <div class="detail-form-grid-3">
      <div class="detail-form-field">
        <label for="detail-input-label">Tên account</label>
        <input type="text" id="detail-input-label" value="${escapeHtml(data.label || "")}" placeholder="VD: Nick chính, Profile 1">
      </div>
      <div class="detail-form-field">
        <label for="detail-input-email">Email</label>
        <input type="text" id="detail-input-email" value="${escapeHtml(data.email || data.username || "")}" placeholder="Email hoặc UID">
      </div>
      <div class="detail-form-field">
        <label for="detail-input-recovery-email">Recovery email</label>
        <input type="text" id="detail-input-recovery-email" value="${escapeHtml(data.recovery_email || data.email_pass || "")}" placeholder="Email khôi phục">
      </div>
    </div>

    <!-- Form Row 2: Password, 2FA, Chrome worker -->
    <div class="detail-form-grid-3">
      <div class="detail-form-field">
        <label for="detail-input-password">Password</label>
        <div class="input-with-action">
          <input type="password" id="detail-input-password" value="" placeholder="${passwordPlaceholder}" oninput="markSecretAsLocallyEdited(this)">
          <button type="button" class="btn-field-action" id="btn-toggle-password" onclick="toggleSecretVisibility('detail-input-password', 'password', this)">Show</button>
        </div>
      </div>
      <div class="detail-form-field">
        <label for="detail-input-2fa">2FA / TOTP secret (Base32)</label>
        <div class="input-with-action">
          <input type="password" id="detail-input-2fa" value="" placeholder="${faPlaceholder}" oninput="markSecretAsLocallyEdited(this)">
          <button type="button" class="btn-field-action" id="btn-toggle-2fa" onclick="toggleSecretVisibility('detail-input-2fa', 'secret_2fa', this)">Show</button>
        </div>
      </div>
      <div class="detail-form-field">
        <label for="detail-input-worker">Chrome worker</label>
        <input type="text" id="detail-input-worker" value="tinix-03 · CDP ${port}" readonly title="${escapeHtml(data.profile_dir || "")}">
      </div>
    </div>

    <!-- Form Row 3: Recovery codes -->
    <div class="detail-form-field detail-full-width-field">
      <label for="detail-input-recovery-codes">Recovery codes (mỗi mã một dòng)</label>
      <div class="input-with-action"><textarea id="detail-input-recovery-codes" rows="3" placeholder="${recoveryCodesPlaceholder}" oninput="markSecretAsLocallyEdited(this)"></textarea><button type="button" class="btn-field-action" onclick="toggleSecretVisibility('detail-input-recovery-codes', 'recovery_codes', this)">Show</button></div>
    </div>

    <!-- Form Row 4: Cookie Facebook -->
    <div class="detail-form-field detail-full-width-field">
      <label for="detail-input-cookie">Cookie Facebook</label>
      <div class="input-with-action"><textarea id="detail-input-cookie" rows="3" placeholder="${cookiePlaceholder}" oninput="markSecretAsLocallyEdited(this)"></textarea><button type="button" class="btn-field-action" onclick="toggleSecretVisibility('detail-input-cookie', 'cookie', this)">Show</button></div>
    </div>

    <!-- Form Row 5: Notes -->
    <div class="detail-form-field detail-full-width-field">
      <label for="detail-input-notes">Notes</label>
      <textarea id="detail-input-notes" rows="3" placeholder="Ghi chú về tài khoản này...">${escapeHtml(data.notes || "")}</textarea>
    </div>

    <!-- Detail Footer Bar -->
    <div class="detail-footer-bar">
      <div>
        ${!isNew ? `<button type="button" class="btn-outline-danger" onclick="clearAccountCredentialsAction(${accId})">Clear Credentials</button>` : ""}
      </div>
      <div class="detail-footer-right">
        <span class="detail-saved-indicator" id="detail-saved-indicator">✓ Saved</span>
        ${!isNew ? `
          <button type="button" class="btn btn-teal btn-sm" onclick="launchAccountChrome(${accId})">🌐 Mở Chrome</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="closeAccountChrome(${accId})">✕ Đóng Chrome</button>
        ` : ""}
        <button type="button" class="btn btn-primary" id="btn-detail-save" onclick="saveDetailAccount(${isNew ? "'new'" : accId})">${isNew ? "💾 Tạo Tài Khoản" : "💾 Lưu Thay Đổi"}</button>
      </div>
    </div>
  `;
}

async function checkAccountPreflight(accId, triggerButton = null) {
  const button = triggerButton;
  const isCurrentDetailAccount = Number(state.selectedAccountId) === Number(accId);
  const statusText = isCurrentDetailAccount ? document.getElementById("detail-status-text") : null;
  const statusBanner = isCurrentDetailAccount ? document.getElementById("detail-status-banner") : null;
  if (button) {
    button.disabled = true;
    button.textContent = "Đang kiểm tra...";
  }
  if (statusText) statusText.textContent = "Đang chạy preflight: kiểm tra Chrome và phiên Facebook...";
  try {
    const response = await fetch(`/api/accounts/${Number(accId)}/preflight`, { method: "POST" });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Không thể check preflight");
    const data = result.data || {};
    applyAccountPreflightResult(accId, data);
    if (statusText) statusText.textContent = `[${data.code || "UNKNOWN"}] ${data.message || "Không có kết quả"}`;
    if (statusBanner) statusBanner.classList.toggle("running", Boolean(data.ready));
    showToast(
      data.ready ? "Account sẵn sàng nhận bài tải." : (data.message || "Account chưa sẵn sàng."),
      data.ready ? "success" : "warning"
    );
  } catch (error) {
    if (statusText) statusText.textContent = `Preflight không hoàn tất: ${error.message || "Lỗi kết nối"}`;
    if (statusBanner) statusBanner.classList.remove("running");
    showToast(error.message || "Không thể check preflight", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "✓ Check Preflight";
    }
  }
}

function renderDetailEmptyState() {
  const container = document.getElementById("account-detail-container");
  if (!container) return;
  container.innerHTML = `
    <div class="detail-empty-state">
      <div class="detail-empty-icon">👥</div>
      <div class="detail-empty-title">Chưa chọn tài khoản</div>
      <div class="detail-empty-desc">
        Chọn một tài khoản từ danh sách bên cột trái để xem và chỉnh sửa thông tin trực tiếp, hoặc nhấn nút <strong>"➕ Thêm Account"</strong> để tạo mới.
      </div>
      <button type="button" class="btn btn-primary btn-sm" onclick="createNewAccountView()">➕ Thêm Account Ngay</button>
    </div>
  `;
}

function createNewAccountView() {
  state.selectedAccountId = "new";

  document.querySelectorAll(".account-card").forEach(card => card.classList.remove("selected"));

  renderAccountDetail({
    label: "",
    username: "",
    email: "",
    recovery_email: "",
    password: "",
    secret_2fa: "",
    cookie: "",
    recovery_codes: "",
    notes: "",
    is_active: 1,
    port: 9400,
    is_chrome_running: false
  }, true);

  setTimeout(() => {
    document.getElementById("detail-input-label")?.focus();
  }, 50);
}

async function toggleSecretVisibility(inputId, secretName, btnEl) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const isVisible = input.dataset.secretVisible === "true";
  if (isVisible) {
    if (input.tagName === "INPUT") input.type = "password";
    if (input.dataset.secretSource === "revealed") input.value = "";
    delete input.dataset.secretVisible;
    delete input.dataset.secretSource;
    btnEl.textContent = "Show";
    return;
  }

  if (!input.value && state.selectedAccountId && state.selectedAccountId !== "new") {
    try {
      const res = await fetch(`/api/accounts/${state.selectedAccountId}/secret/${secretName}`, { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(json.detail || "Không thể hiển thị credential", "error");
        return;
      }
      input.value = json.data?.value || "";
      input.dataset.secretSource = "revealed";
    } catch (e) {
      showToast("Lỗi kết nối khi hiển thị credential", "error");
      return;
    }
  }
  if (input.tagName === "INPUT") input.type = "text";
  input.dataset.secretVisible = "true";
  btnEl.textContent = "Hide";
}

function markSecretAsLocallyEdited(input) {
  if (input?.dataset?.secretSource === "revealed") {
    input.dataset.secretSource = "edited";
  }
}

function toggleAccountFavorite(event, accId) {
  event.stopPropagation();
  const idNum = Number(accId);
  if (state.accountFavorites.has(idNum)) {
    state.accountFavorites.delete(idNum);
  } else {
    state.accountFavorites.add(idNum);
  }
  localStorage.setItem("tinix.account.favorites", JSON.stringify([...state.accountFavorites]));
  renderAccountsList();
}

function toggleSplitterPane() {
  const pane = document.getElementById("account-list-pane");
  const arrow = document.getElementById("splitter-arrow");
  if (!pane || !arrow) return;
  state.accountListCollapsed = !state.accountListCollapsed;
  pane.classList.toggle("collapsed", state.accountListCollapsed);
  arrow.textContent = state.accountListCollapsed ? "▶" : "◀";
}

function showSavedIndicator() {
  const indicator = document.getElementById("detail-saved-indicator");
  if (indicator) {
    indicator.classList.add("show");
    setTimeout(() => {
      indicator.classList.remove("show");
    }, 2500);
  }
}

async function onAccountActiveToggle() {
  if (!state.selectedAccountId || state.selectedAccountId === "new") return;
  const isActive = document.getElementById("detail-input-active")?.checked ?? true;
  try {
    const res = await fetch("/api/accounts/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: Number(state.selectedAccountId), is_active: isActive })
    });
    if (res.ok) {
      showSavedIndicator();
      showToast(`Đã ${isActive ? "kích hoạt" : "tạm dừng"} tài khoản`, "info");
      await loadAccounts();
    }
  } catch (e) {}
}

async function clearAccountCredentialsAction(accId) {
  if (!accId || accId === "new") return;
  if (!confirm("Bạn có chắc muốn xóa mật khẩu, 2FA, cookie và recovery codes của tài khoản này?")) return;
  try {
    const res = await fetch("/api/accounts/clear-credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: Number(accId) })
    });
    if (res.ok) {
      const pwdInput = document.getElementById("detail-input-password");
      const faInput = document.getElementById("detail-input-2fa");
      const cookieInput = document.getElementById("detail-input-cookie");
      const recInput = document.getElementById("detail-input-recovery-codes");
      if (pwdInput) { pwdInput.value = ""; pwdInput.placeholder = "Chưa lưu"; }
      if (faInput) { faInput.value = ""; faInput.placeholder = "Chưa lưu"; }
      if (cookieInput) cookieInput.value = "";
      if (recInput) recInput.value = "";
      showSavedIndicator();
      showToast("Đã xóa toàn bộ credentials của tài khoản", "success");
      await loadAccounts();
    } else {
      const json = await res.json();
      showToast(json.detail || "Không thể xóa credentials", "error");
    }
  } catch (e) {
    showToast("Lỗi kết nối khi xóa credentials", "error");
  }
}

async function saveDetailAccount(accId = null) {
  const label = document.getElementById("detail-input-label")?.value.trim() || "";
  const email = document.getElementById("detail-input-email")?.value.trim() || "";
  const recoveryEmail = document.getElementById("detail-input-recovery-email")?.value.trim() || "";
  const password = document.getElementById("detail-input-password")?.value || "";
  const secret2fa = document.getElementById("detail-input-2fa")?.value.trim() || "";
  const recoveryCodes = document.getElementById("detail-input-recovery-codes")?.value || "";
  const cookie = document.getElementById("detail-input-cookie")?.value.trim() || "";
  const notes = document.getElementById("detail-input-notes")?.value || "";
  const isActive = document.getElementById("detail-input-active")?.checked ?? true;

  if (!label && !email) {
    showToast("Vui lòng nhập Tên account hoặc Email/UID!", "warning");
    return;
  }

  const payload = {
    label: label || email,
    username: email || label,
    email: email,
    recovery_email: recoveryEmail,
    notes: notes,
    is_active: isActive
  };

  const isNew = accId === null || accId === "new";
  if (!isNew) {
    payload.id = Number(accId);
    if (password) payload.password = password;
    if (secret2fa) payload.secret_2fa = secret2fa;
    if (cookie) payload.cookie = cookie;
    if (recoveryCodes) payload.recovery_codes = recoveryCodes;
  } else {
    payload.password = password;
    payload.secret_2fa = secret2fa;
    payload.cookie = cookie;
    payload.recovery_codes = recoveryCodes;
  }

  const saveBtn = document.getElementById("btn-detail-save");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "⏳ Đang lưu...";
  }

  try {
    const res = await fetch("/api/accounts/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    if (res.ok) {
      const targetId = json.id || accId;
      state.selectedAccountId = Number(targetId);
      showSavedIndicator();
      showToast(isNew ? "Đã tạo tài khoản mới thành công!" : "Đã cập nhật tài khoản!", "success");
      await loadAccounts();
      if (targetId) {
        await loadAccountDetail(targetId);
      }
      fetchStats();
    } else {
      showToast(json.detail || "Không thể lưu tài khoản", "error");
    }
  } catch (e) {
    showToast("Lỗi kết nối khi lưu tài khoản", "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = isNew ? "💾 Tạo Tài Khoản" : "💾 Lưu Thay Đổi";
    }
  }
}

async function launchAccountChrome(accId) {
  const displayId = getAccountDisplayId(accId);
  showToast(`Đang mở Chrome Profile #${displayId}...`, "info");
  try {
    const res = await fetch("/api/accounts/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId })
    });
    const json = await res.json();
    const browserLabel = json.browser_label || "Chrome";
    showToast(res.ok ? `Đã mở ${browserLabel} Profile #${displayId}` : (json.detail || "Không thể mở Chrome"), res.ok ? "success" : "error");
    if (res.ok && Number(state.selectedAccountId) === Number(accId)) {
      loadAccountDetail(accId);
    }
  } catch (e) {
    showToast("Lỗi kết nối khi mở Chrome", "error");
  }
}

async function closeAccountChrome(accId) {
  try {
    const res = await fetch("/api/accounts/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId })
    });
    const json = await res.json();
    showToast(res.ok ? json.message : (json.detail || "Không thể đóng Chrome"), res.ok ? "success" : "error");
    if (res.ok && Number(state.selectedAccountId) === Number(accId)) {
      loadAccountDetail(accId);
    }
  } catch (e) {
    showToast("Lỗi kết nối khi đóng Chrome", "error");
  }
}

async function closeAllAccountChrome() {
  try {
    const res = await fetch("/api/accounts/close-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const json = await res.json();
    showToast(res.ok ? `Đã đóng ${json.closed_count || 0} cửa sổ Chrome` : (json.detail || "Không thể đóng Chrome"), res.ok ? "success" : "error");
  } catch (e) {
    showToast("Lỗi kết nối khi đóng tất cả Chrome", "error");
  }
}

async function exportAccountProfile(accId) {
  const account = state.accounts.find(item => Number(item.id) === Number(accId));
  const name = account?.label || account?.username || `Account #${accId}`;
  if (!confirm(`Export account “${name}” cùng Chrome profile? Hãy đóng Chrome của account trước.`)) return;
  // Credentials stay out of the file unless the user explicitly opts in. The Chrome session is always included.
  const includeSecrets = confirm(
    "Đưa mật khẩu, mã 2FA, email pass và cookie vào file?\n\n" +
    "OK = có (file chứa dữ liệu đăng nhập đầy đủ).\nCancel = không (file vẫn chứa phiên Chrome)."
  );
  try {
    const res = await fetch("/api/accounts/profile/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId, include_secrets: includeSecrets })
    });
    const json = await res.json();
    showToast(res.ok ? `Đã Export: ${json.bundle_path}` : (json.detail || "Không thể Export profile"), res.ok ? "success" : "error");
  } catch (e) {
    showToast("Lỗi kết nối khi Export profile", "error");
  }
}

async function exportAllAccountProfiles() {
  if (!state.accounts.length) {
    showToast("Chưa có account để Export profile", "warning");
    return;
  }
  const button = document.getElementById("btn-export-profile");
  const originalLabel = button?.textContent || "⬆ Export Account & Sessions ZIP";
  if (button) {
    button.disabled = true;
    button.textContent = "⏳ Đang sao chép và nén...";
  }
  const includeSecrets = confirm(
    "Đưa mật khẩu, mã 2FA, email pass và cookie của TẤT CẢ account vào file ZIP?\n\n" +
    "OK = có.\nCancel = không (ZIP vẫn chứa phiên Chrome)."
  );
  showToast("Đang Export thông tin account và phiên Chrome. File ZIP chứa phiên đăng nhập, hãy bảo quản cẩn thận...", "info");
  try {
    const res = await fetch(`/api/accounts/profile/export-all?include_secrets=${includeSecrets ? "true" : "false"}`, {method: "POST"});
    const json = await res.json();
    showToast(res.ok ? `Đã Export ${json.accounts_exported} profile: ${json.archive_path}` : (json.detail || "Không thể Export profiles"), res.ok ? "success" : "error");
  } catch (e) {
    showToast("Lỗi kết nối khi Export profiles", "error");
  } finally {
    if (button) {
      button.textContent = originalLabel;
      button.disabled = state.accounts.length === 0;
    }
  }
}

function formatProfileBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function previewProfilesCleanup() {
  try {
    const res = await fetch("/api/accounts/profile/cleanup-preview");
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể quét profile", "error");
      return;
    }
    let summary = `Có thể giải phóng khoảng <strong>${formatProfileBytes(json.bytes_removable)}</strong> (${json.files_removable} file) trong ${json.profiles_scanned} profile.`;
    if (json.chrome_running) summary += `<br><span class="text-danger">Có ${json.chrome_running} profile đang được Chrome sử dụng. Hãy đóng Chrome trước.</span>`;
    if (!json.bytes_removable) summary += `<br>Hiện không có dữ liệu cần dọn.`;
    const disabled = json.chrome_running || !json.bytes_removable ? "disabled" : "";
    openModal("🧹 Dọn dẹp Chrome profile", `
      <div class="account-editor-form">
        <p>${summary}</p>
        <small>Chỉ xóa cache, model và dữ liệu tạm có thể tạo lại. Cookies, phiên đăng nhập, Local Storage, IndexedDB và thông tin account được giữ nguyên.</small>
      </div>
    `, `
      <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
      <button class="btn btn-danger" id="confirm-profile-cleanup" onclick="runProfilesCleanup()" ${disabled}>Dọn dẹp ngay</button>
    `);
  } catch (e) {
    showToast("Lỗi kết nối khi quét profile", "error");
  }
}

async function runProfilesCleanup() {
  const button = document.getElementById("confirm-profile-cleanup");
  if (button) {
    button.disabled = true;
    button.textContent = "Đang dọn dẹp...";
  }
  try {
    const res = await fetch("/api/accounts/profile/cleanup", {method: "POST"});
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể dọn profile", "error");
      return;
    }
    closeModal();
    showToast(`Đã dọn ${json.profiles_cleaned} profile, giải phóng ${formatProfileBytes(json.bytes_freed)}`, "success");
  } catch (e) {
    showToast("Lỗi kết nối khi dọn profile", "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "Dọn dẹp ngay";
    }
  }
}

function importAccountProfile() {
  openModal("⬇ Import Profiles ZIP", `
    <div class="account-editor-form">
      <label>
        <span>Đường dẫn file ZIP</span>
        <input type="text" id="profile-zip-path" placeholder="D:\\...\\Tinix-...-all-profiles.tinix-profiles.zip">
        <small>FB Down sẽ Import toàn bộ profile Facebook; các nền tảng khác sẽ được bỏ qua.</small>
      </label>
    </div>
  `, `
    <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
    <button class="btn btn-primary" onclick="submitProfilesZipImport()">Bắt đầu Import</button>
  `);
  setTimeout(() => document.getElementById("profile-zip-path")?.focus(), 0);
}

async function submitProfilesZipImport() {
  const bundlePath = document.getElementById("profile-zip-path")?.value.trim();
  if (!bundlePath) {
    showToast("Hãy nhập đường dẫn file .tinix-profiles.zip", "warning");
    return;
  }
  closeModal();
  showToast("Đang Import các account/profile. Vui lòng chờ...", "info");
  try {
    const res = await fetch("/api/accounts/profile/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundle_path: bundlePath })
    });
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể Import profile", "error");
      return;
    }
    await loadAccounts();
    fetchStats();
    const count = json.accounts_imported || 1;
    const skipped = json.profiles_skipped ? `; bỏ qua ${json.profiles_skipped} profile không phải Facebook` : "";
    showToast(`Đã Import ${count} account/profile${skipped}`, "success");
  } catch (e) {
    showToast("Lỗi kết nối khi Import profile", "error");
  }
}

async function deleteAccount(accId) {
  const displayId = getAccountDisplayId(accId);
  if (!confirm(`Bạn có chắc muốn xóa tài khoản #${displayId}?`)) return;
  // Chrome profile keeps login cookies on disk; removing it is a separate, explicit choice (default: keep).
  const deleteProfile = confirm(
    `Xóa luôn Chrome profile của tài khoản #${displayId} trên máy này?\n\n` +
    "Profile chứa cookie đăng nhập Facebook. Chọn Cancel để giữ profile."
  );
  try {
    const res = await fetch("/api/accounts/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId, delete_profile: deleteProfile })
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      // Do not report success when the account was not deleted (e.g. profile busy, outside managed root).
      showToast(json.detail || "Không xóa được tài khoản", "error");
      return;
    }
    if (Number(state.selectedAccountId) === Number(accId)) {
      state.selectedAccountId = null;
    }
    await loadAccounts();
    fetchStats();
    if (json.status === "partial") {
      // The account row is gone but its profile folder remains: warn, do not report a clean success.
      showToast(json.message || "Đã xóa tài khoản nhưng còn thư mục profile", "warning");
      return;
    }
    showToast(json.profile_deleted ? "Đã xóa tài khoản và Chrome profile" : "Đã xóa tài khoản", "info");
  } catch (e) {
    showToast("Lỗi kết nối khi xóa tài khoản", "error");
  }
}

function getAccountDisplayId(accId) {
  const index = state.accounts.findIndex(item => Number(item.id) === Number(accId));
  return index >= 0 ? index + 1 : Number(accId) || 0;
}

function openAccountEditor(accId = null) {
  if (accId === null) {
    createNewAccountView();
  } else {
    selectAccount(accId);
  }
}

function initAccountsMasterDetail() {
  const searchInput = document.getElementById("acc-search-input");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.accountSearchQuery = e.target.value;
      renderAccountsList();
    });
  }

  const statusFilter = document.getElementById("acc-status-filter");
  if (statusFilter) {
    statusFilter.addEventListener("change", (e) => {
      state.accountStatusFilter = e.target.value;
      renderAccountsList();
    });
  }

  const sortSelect = document.getElementById("acc-sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      state.accountSort = e.target.value;
      renderAccountsList();
    });
  }

  const filterTabs = document.getElementById("account-filter-tabs");
  if (filterTabs) {
    filterTabs.querySelectorAll(".acc-tab-pill").forEach(pill => {
      pill.addEventListener("click", () => {
        filterTabs.querySelectorAll(".acc-tab-pill").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        state.accountTabFilter = pill.dataset.filter || "all";
        renderAccountsList();
      });
    });
  }

  const splitterBtn = document.getElementById("btn-toggle-splitter");
  if (splitterBtn) {
    splitterBtn.addEventListener("click", toggleSplitterPane);
  }
}

// ─── Modal & Toasts Helpers ─────────────────────────────────────────────────

function openModal(title, bodyHtml, footerHtml, { spyIndex = null } = {}) {
  state.spyModalIndex = spyIndex;
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-footer").innerHTML = footerHtml;
  document.getElementById("generic-modal").classList.add("active");
}

function closeModal() {
  const modal = document.getElementById("generic-modal");
  modal.querySelectorAll("video").forEach(video => video.pause());
  modal.classList.remove("active");
  state.spyModalIndex = null;
  state.spyModalDeleting = false;
  state.spyModalRequest += 1;
}

function handleModalKeyboard(event) {
  const modal = document.getElementById("generic-modal");
  if (!modal.classList.contains("active")) return;
  const target = event.target;
  if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModal();
    return;
  }
  if (state.spyModalIndex === null) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    navigateSpyModal(event.key === "ArrowLeft" ? -1 : 1);
  } else if (event.key === "Delete") {
    event.preventDefault();
    deleteCurrentSpyPost();
  } else if (/^[1-5]$/.test(event.key)) {
    event.preventDefault();
    rateCurrentSpyPost(Number(event.key));
  }
}

function showToast(message, type = "info") {
  if (type === "error" || type === "warning") {
    setAppActivity({
      type,
      title: type === "error" ? "Có lỗi xảy ra" : "Cần lưu ý",
      message: String(message || "")
    });
  }
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;

  if (type === "success") toast.style.borderLeftColor = "var(--success-green)";
  if (type === "error") toast.style.borderLeftColor = "var(--danger-red)";
  if (type === "warning") toast.style.borderLeftColor = "var(--warning-amber)";

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ─── Initial Startup ────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  initGlobalApiNotifications();
  document.getElementById("btn-dismiss-app-activity")?.addEventListener("click", resetAppActivity);
  initWebSocket();
  initTabs();
  initCollapsiblePanels();
  initDownloader();
  initScraper();
  initScrapeExecutionSettings();
  initAccountsMasterDetail();
  document.getElementById("btn-recheck-system-readiness")?.addEventListener("click", loadAppVersion);
  loadConfig();
  loadAppVersion();
  fetchStats();
  loadRecentTaskRuns();
  refreshPendingAutoDownloads();
  setInterval(pollFavoriteScanStatus, 2500);
  setInterval(refreshPendingAutoDownloads, 2500);
  setInterval(loadRecentTaskRuns, 10000);

  document.getElementById("btn-clear-logs").addEventListener("click", () => {
    document.getElementById("terminal-logs").innerHTML = "";
  });

  const sidebarOutputInput = document.getElementById("sidebar-output-dir");
  sidebarOutputInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    event.currentTarget.blur();
  });
  sidebarOutputInput.addEventListener("change", async (event) => {
    const path = event.currentTarget.value.trim();
    if (path && path !== String(state.config.output_dir || "").trim()) {
      await saveOutputDirectory(path);
    }
  });

  document.getElementById("btn-select-output-dir").addEventListener("click", async () => {
    const button = document.getElementById("btn-select-output-dir");
    button.disabled = true;
    try {
      const res = await fetch("/api/system/select-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_path: document.getElementById("sidebar-output-dir").value.trim() || null })
      });
      const json = await res.json();
      if (!res.ok) {
        showToast(json.detail || "Không thể mở hộp thoại chọn thư mục.", "error");
      } else if (json.status === "success") {
        document.getElementById("sidebar-output-dir").value = json.path;
        await saveOutputDirectory(json.path);
      }
    } catch (e) {
      showToast("Lỗi kết nối khi chọn thư mục.", "error");
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("btn-open-output-dir").addEventListener("click", async () => {
    const path = document.getElementById("sidebar-output-dir").value.trim();
    if (!(await saveOutputDirectory(path, { quiet: true }))) return;
    await fetch("/api/system/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: state.config.output_dir }) });
  });

  document.getElementById("btn-close-modal").addEventListener("click", closeModal);
  document.getElementById("generic-modal").addEventListener("click", event => {
    if (event.target === event.currentTarget) closeModal();
  });
  document.addEventListener("keydown", handleModalKeyboard);
  document.getElementById("btn-close-all-chrome").addEventListener("click", closeAllAccountChrome);

  // Settings Modal
  document.getElementById("btn-settings-modal")?.addEventListener("click", () => {
    openModal("⚙️ Cài Đặt Hệ Thống", `
      <div style="display: flex; flex-direction: column; gap: 14px;">
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Thư mục lưu tải về:</label>
          <input type="text" id="setting-output-dir" value="${escapeHtml(state.config.output_dir || '.')}">
        </div>
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Số luồng tải mặc định:</label>
        <input type="number" id="setting-max-threads" value="${state.config.max_threads || 3}" min="1" max="16">
        </div>
        <div>
          <label class="custom-checkbox">
            <input type="checkbox" id="setting-auto-open" ${state.config.auto_open_folder ? 'checked' : ''}>
            <span>Tự động mở thư mục sau khi tải xong</span>
          </label>
        </div>
        <div class="text-muted" style="font-size:12px; line-height:1.5;">
          Mặc định an toàn là 3 account worker. Từ 4 worker trở lên sẽ tăng nguy cơ Facebook yêu cầu xác nhận lại.
        </div>
        <div style="padding:12px; border:1px solid var(--border-subtle); border-radius:8px;">
          <div style="font-weight:700; font-size:12.5px; margin-bottom:5px;">Bảo mật dữ liệu đăng nhập</div>
          <div class="text-muted" style="font-size:12px; margin-bottom:8px;">Tạo backup rồi mã hóa cookie, mật khẩu, 2FA và token bằng Windows DPAPI. Database sau đó chỉ giải mã được bởi tài khoản Windows hiện tại.</div>
          <button type="button" class="btn btn-secondary btn-sm" onclick="migrateSecureStorage()">🔐 Mã hóa secrets hiện có</button>
        </div>
      </div>
    `, `
      <button class="btn btn-secondary" onclick="closeModal()">Đóng</button>
      <button class="btn btn-primary" onclick="saveSettings()">Lưu Cài Đặt</button>
    `);
  });

  // Add Account Modal
  document.getElementById("btn-add-account").addEventListener("click", () => {
    openAccountEditor();
  });
  document.getElementById("btn-import-profile").addEventListener("click", importAccountProfile);
  document.getElementById("btn-export-profile").addEventListener("click", exportAllAccountProfiles);
  document.getElementById("btn-cleanup-profiles").addEventListener("click", previewProfilesCleanup);

  // Spy Filter Realtime Controls
  const btnRefreshSpy = document.getElementById("btn-refresh-spy");
  if (btnRefreshSpy) {
    btnRefreshSpy.addEventListener("click", loadSpyPosts);
  }
  const spyMode = document.getElementById("spy-mode");
  if (spyMode) {
    spyMode.addEventListener("change", applySpyModeSelection);
  }
  const spyPostType = document.getElementById("spy-post-type");
  if (spyPostType) {
    spyPostType.addEventListener("change", loadSpyPosts);
  }
  const spyDlStatus = document.getElementById("spy-dl-status");
  if (spyDlStatus) {
    spyDlStatus.addEventListener("change", loadSpyPosts);
  }
  const spySearch = document.getElementById("spy-search");
  if (spySearch) {
    let spySearchTimer = null;
    spySearch.addEventListener("input", () => {
      clearTimeout(spySearchTimer);
      spySearchTimer = setTimeout(() => {
        loadSpyPosts();
      }, 300);
    });
    spySearch.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        clearTimeout(spySearchTimer);
        loadSpyPosts();
      }
    });
  }
  document.getElementById("spy-select-all-posts").addEventListener("change", event => selectAllSpyPosts(event.target.checked));
  document.getElementById("btn-download-spy-posts").addEventListener("click", downloadSelectedSpyPosts);
  document.getElementById("btn-retry-spy-posts").addEventListener("click", retrySelectedSpyPosts);
  document.getElementById("btn-delete-spy-posts").addEventListener("click", deleteSelectedSpyPosts);
  const spyPageFilter = document.getElementById("spy-page-filter");
  if (spyPageFilter) {
    spyPageFilter.addEventListener("change", () => {
      syncSpySelectedPagesFromDropdown();
      loadSpyPosts();
    });
  }


  // View toggle in Spy
  document.getElementById("btn-view-grid").addEventListener("click", () => {
    setSpyView("grid");
  });

  document.getElementById("btn-view-table").addEventListener("click", () => {
    setSpyView("table");
  });

  // Export Excel in Spy
  document.getElementById("btn-export-excel").addEventListener("click", async () => {
    if (!state.selectedPageNames.length) {
      showToast("Vui lòng chọn ít nhất 1 page để xuất Excel!", "warning");
      return;
    }
    showToast("Đang tạo file Excel...", "info");
    try {
      const res = await fetch("/api/spy/export-excel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_names: state.selectedPageNames,
          mode: document.getElementById("spy-mode").value,
          post_type: document.getElementById("spy-post-type").value,
          download_status: document.getElementById("spy-dl-status").value,
          sort_by: state.spySort.key,
          sort_order: state.spySort.direction
        })
      });
      const json = await res.json();
      if (res.ok) {
        showToast(`Đã xuất: ${json.filename}`, "success");
      } else {
        showToast(json.detail || "Lỗi xuất file", "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", "error");
    }
  });
});

async function saveSettings() {
  const outDir = document.getElementById("setting-output-dir").value.trim();
  const threads = parseInt(document.getElementById("setting-max-threads").value) || 3;
  const autoOpen = document.getElementById("setting-auto-open").checked;

  try {
    const res = await fetch("/api/system/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        output_dir: outDir,
        max_threads: threads,
        auto_open_folder: autoOpen
      })
    });
    if (res.ok) {
      const json = await res.json();
      state.config = { ...state.config, ...json.data };
      syncOutputDirectoryInputs();
      closeModal();
      showToast("Đã lưu cài đặt hệ thống!", "success");
    }
  } catch (e) {}
}

async function migrateSecureStorage() {
  const accepted = window.confirm(
    "Ứng dụng sẽ tạo backup database rồi mã hóa secrets bằng tài khoản Windows hiện tại. " +
    "Database đã mã hóa không thể chuyển sang tài khoản Windows khác nếu không khôi phục backup. Tiếp tục?"
  );
  if (!accepted) return;
  try {
    const response = await fetch("/api/system/secure-storage/migrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true })
    });
    const result = await response.json();
    if (!response.ok) {
      showToast(result.detail || "Không thể mã hóa secrets", "error");
      return;
    }
    appendLog(`Đã mã hóa ${result.changed} secrets. Backup: ${result.backup_path}`, "OK");
    showToast(`Đã mã hóa ${result.changed} secrets và tạo backup`, "success");
  } catch (error) {
    showToast("Lỗi kết nối khi mã hóa secrets", "error");
  }
}

async function submitAccount(accId = null) {
  const label = document.getElementById("acc-label").value.trim();
  const username = document.getElementById("acc-username").value.trim();
  const password = document.getElementById("acc-password").value.trim();
  const secret2fa = document.getElementById("acc-2fa").value.trim();
  const cookie = document.getElementById("acc-cookie").value.trim();
  const isActive = document.getElementById("acc-active").checked;

  if (!label && !username) {
    showToast("Vui lòng nhập Tên gợi nhớ hoặc Username!", "warning");
    return;
  }

  try {
    const payload = { label, username, is_active: isActive };
    if (accId !== null) payload.id = Number(accId);
    if (accId === null || password) payload.password = password;
    if (accId === null || secret2fa) payload.secret_2fa = secret2fa;
    if (accId === null || cookie) payload.cookie = cookie;

    const res = await fetch("/api/accounts/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const json = await res.json();
    if (res.ok) {
      closeModal();
      await loadAccounts();
      await fetchStats();
      showToast(accId === null ? "Đã thêm tài khoản mới!" : "Đã cập nhật tài khoản!", "success");
    } else {
      showToast(json.detail || "Không thể lưu tài khoản", "error");
    }
  } catch (e) {
    showToast("Lỗi kết nối khi lưu tài khoản", "error");
  }
}
