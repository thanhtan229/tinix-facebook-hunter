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
  accounts: [],
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
  spyModalIndex: null,
  spyModalRequest: 0,
  spyModalDeleting: false,
  config: {},
  pendingCleanup: null
};

const TAB2_PANEL_STORAGE_KEY = "tinix.tab2.collapsed-panels";
const TAB2_AUTO_DOWNLOAD_STORAGE_KEY = "tinix.tab2.auto-download";
const FAVORITE_GROUP_FILTER_STORAGE_KEY = "tinix.tab2.favorite-group-filter";

function isAutoDownloadEnabled() {
  return Boolean(document.getElementById("scrape-auto-download")?.checked);
}

function updateAutoDownloadUi() {
  const enabled = isAutoDownloadEnabled();
  const status = document.getElementById("scrape-auto-download-status");
  if (status) {
    status.textContent = enabled ? "Đang bật" : "Đang tắt";
    status.className = `badge ${enabled ? "badge-green" : "badge-gray"}`;
  }
}

function initAutoDownloadOption() {
  const checkbox = document.getElementById("scrape-auto-download");
  if (!checkbox) return;
  try { checkbox.checked = localStorage.getItem(TAB2_AUTO_DOWNLOAD_STORAGE_KEY) === "true"; } catch (_) {}
  updateAutoDownloadUi();
  checkbox.addEventListener("change", () => {
    try { localStorage.setItem(TAB2_AUTO_DOWNLOAD_STORAGE_KEY, String(checkbox.checked)); } catch (_) {}
    updateAutoDownloadUi();
    showToast(checkbox.checked ? "Đã bật Auto Download" : "Đã tắt Auto Download", "info");
  });
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
    scanLimit: Math.max(5, Math.min(parseInt(document.getElementById("scrape-common-limit")?.value) || 100, 2000))
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
      } else if (data.type === "progress") {
        handleProgressUpdate(data);
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

  const timeStr = new Date().toLocaleTimeString();
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

// ─── Tab Switching ──────────────────────────────────────────────────────────

function initTabs() {
  const navItems = document.querySelectorAll(".nav-item");
  const panels = document.querySelectorAll(".tab-panel");
  const title = document.getElementById("current-tab-title");

  const tabTitles = {
    "tab-downloader": "📥 Tải Facebook — Media Downloader",
    "tab-scraper": "🔍 Quét Page — Facebook Page Scraper",
    "tab-spy": "📊 Kho Dữ Liệu — Spy Studio",
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
    }
  } catch (e) {}
}

async function loadAppVersion() {
  const badge = document.getElementById("app-version-badge");
  if (!badge) return;
  try {
    const res = await fetch("/api/system/health");
    const json = await res.json();
    const version = json?.data?.version;
    if (res.ok && version) {
      badge.textContent = `v${version}`;
      badge.title = `Tinix-Facebook-Hunter phiên bản ${version}`;
    }
  } catch (_) {
    badge.textContent = "Version";
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

function initDownloader() {
  document.getElementById("btn-start-dl").addEventListener("click", async () => {
    const urls = document.getElementById("dl-urls").value.trim();
    if (!urls) {
      showToast("Vui lòng nhập ít nhất 1 link Facebook!", "warning");
      return;
    }

    const threads = parseInt(document.getElementById("dl-threads").value);
    const useAccounts = document.getElementById("dl-use-accounts").checked;

    try {
      const res = await fetch("/api/download/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls, max_threads: threads, use_accounts: useAccounts })
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

  document.getElementById("btn-pause-dl").addEventListener("click", async () => {
    await fetch("/api/download/pause", { method: "POST" });
  });

  document.getElementById("btn-stop-dl").addEventListener("click", async () => {
    await fetch("/api/download/stop", { method: "POST" });
    showToast("Đã dừng tải xuống", "info");
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

    try {
      const res = await fetch("/api/scrape/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page_urls: pageUrls, mode, limit: settings.scanLimit,
          account_mode: settings.accountMode, account_id: settings.accountId,
          max_concurrency: settings.maxConcurrency,
          download_media: isAutoDownloadEnabled(), delay_mode: settings.delayMode
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
    state.scrapeAccounts = res.ok ? (json.data || []) : [];
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
  if (!confirm(`Quét từ đầu sẽ xóa mốc quét của ${ids.length} Fanpage đã chọn và tạo mốc mới ở lần quét sau. Tiếp tục?`)) return;
  try {
    const res = await fetch("/api/scrape/favorites/batch-reset-cursor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite_ids: ids })
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || "Không thể đặt lại mốc quét");
    showToast(`Đã đặt lại mốc quét cho ${json.count || ids.length} Fanpage`, "success");
    await loadFavoritePages();
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
  try {
    const res = await fetch("/api/scrape/favorites/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        favorite_ids: ids, account_mode: settings.accountMode, account_id: settings.accountId,
        max_concurrency: settings.maxConcurrency, scan_limit: settings.scanLimit,
        download_media: isAutoDownloadEnabled(),
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
  ["scrape-common-account", "scrape-common-concurrency", "scrape-common-delay", "scrape-common-limit", "btn-start-scrape", "btn-start-page-search", "btn-scan-selected-favorites", "btn-scan-older-favorites", "btn-reset-selected-favorites", "btn-delete-selected-favorites", "favorite-group-trigger", "btn-remove-selected-from-group", "btn-create-favorite-group"]
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
  if (status === "Lỗi") return "badge-red";
  return "badge-teal";
}

function renderFavoriteWorkers(workers, isRunning) {
  const panel = document.getElementById("favorite-workers-panel");
  const grid = document.getElementById("favorite-workers-grid");
  if (!panel || !grid) return;
  panel.hidden = !workers.length;
  grid.innerHTML = workers.map(worker => {
    const status = worker.status || "Đang chờ";
    const canStop = isRunning && !["Hoàn tất", "Đã dừng", "Lỗi"].includes(status);
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
  if (!confirm("Quét từ đầu sẽ xóa mốc hiện tại và tạo mốc mới ở lần quét sau. Tiếp tục?")) return;
  try {
    await favoriteAction("reset-cursor", favoriteId);
    showToast("Đã đặt lại mốc quét", "success");
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

// ─── Tab 3: Spy Studio (Kho Dữ Liệu) ────────────────────────────────────────

async function loadSpyPages() {
  try {
    const res = await fetch("/api/spy/pages");
    const json = await res.json();
    if (json.status === "success") {
      state.scrapedPages = json.data;
      renderSpyPageCheckboxes();
      await loadSpyPosts();
    }
  } catch (e) {}
}

function renderSpyPageCheckboxes() {
  const container = document.getElementById("spy-pages-container");
  const counter = document.getElementById("spy-pages-counter");
  container.innerHTML = "";

  counter.textContent = `${state.scrapedPages.length} Pages`;
  state.selectedPageNames = state.scrapedPages.map(p => p.page_name);
  state.selectedPageUrls = state.scrapedPages.map(p => p.page_url);

  state.scrapedPages.forEach(p => {
    const label = document.createElement("label");
    label.className = "custom-checkbox";
    label.style.fontSize = "12px";
    label.innerHTML = `
      <input type="checkbox" value="${escapeHtml(p.page_name)}" checked>
      <span>${escapeHtml(p.page_name)} <small class="text-muted">(${Number(p.post_count) || 0})</small></span>
    `;

    label.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) {
        if (!state.selectedPageNames.includes(p.page_name)) state.selectedPageNames.push(p.page_name);
        if (!state.selectedPageUrls.includes(p.page_url)) state.selectedPageUrls.push(p.page_url);
      } else {
        state.selectedPageNames = state.selectedPageNames.filter(n => n !== p.page_name);
        state.selectedPageUrls = state.selectedPageUrls.filter(url => url !== p.page_url);
      }
      loadSpyPosts();
    });

    container.appendChild(label);
  });
}

async function loadSpyPosts() {
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

  try {
    const res = await fetch("/api/spy/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
    if (json.status === "success") {
      state.spyPosts = json.data;
      state.selectedSpyPostIds.clear();
      renderSpyPostsGrid();
      renderSpyPostsTable();
      syncSpyPostSelectionUi();
      observeSpyLazyMedia();
    }
  } catch (e) {}
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

async function cleanupSpyRepository(allPages) {
  const pageUrls = allPages ? [] : state.selectedPageUrls;
  if (!allPages && !pageUrls.length) {
    showToast("Chọn ít nhất một Page cần xóa", "warning");
    return;
  }
  const scope = { page_urls: pageUrls, all_pages: allPages };
  try {
    const previewResponse = await fetch("/api/spy/cleanup-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scope)
    });
    const previewResult = await previewResponse.json();
    if (!previewResponse.ok) {
      showToast(previewResult.detail || "Không thể kiểm tra dữ liệu cần xóa", "error");
      return;
    }
    const preview = previewResult.data;
    if (!preview.pages && !preview.posts) {
      showToast("Không có dữ liệu phù hợp để dọn", "info");
      return;
    }
    const deleteMedia = document.getElementById("spy-delete-media").checked;
    state.pendingCleanup = { scope, deleteMedia, preview };
    openModal("⚠️ Xác nhận dọn Kho Dữ Liệu", `
      <div style="display:flex; flex-direction:column; gap:14px;">
        <div style="padding:12px; border:1px solid var(--danger); border-radius:8px; background:rgba(220,38,38,.06);">
          <div style="font-weight:700; margin-bottom:6px;">Dữ liệu sẽ bị xóa</div>
          <div>${Number(preview.pages) || 0} Page và ${Number(preview.posts) || 0} bài đã quét</div>
          ${deleteMedia ? `<div>Tối đa ${Number(preview.media_paths) || 0} thư mục media</div>` : ""}
        </div>
        <div class="text-muted" style="font-size:12.5px; line-height:1.5;">
          Ứng dụng tạo và kiểm tra backup database trước khi xóa. Backup không chứa media.
          Tài khoản, token, fanpage quản lý và lịch đăng được giữ nguyên.
        </div>
        <div id="spy-cleanup-error" class="text-muted" style="font-size:12px;"></div>
      </div>
    `, `
      <button class="btn btn-secondary" onclick="cancelSpyCleanup()">Hủy</button>
      <button class="btn btn-danger" id="btn-confirm-spy-cleanup" onclick="executeSpyCleanup()">Xóa dữ liệu</button>
    `);
  } catch (error) {
    console.error("Cleanup preview failed", error);
    showToast(`Không thể kiểm tra dữ liệu: ${error.message || "lỗi không xác định"}`, "error");
  }
}

function cancelSpyCleanup() {
  state.pendingCleanup = null;
  closeModal();
}

async function executeSpyCleanup() {
  const pending = state.pendingCleanup;
  if (!pending) {
    closeModal();
    return;
  }
  const errorBox = document.getElementById("spy-cleanup-error");
  const confirmButton = document.getElementById("btn-confirm-spy-cleanup");
  confirmButton.disabled = true;
  confirmButton.textContent = "Đang backup và dọn...";
  errorBox.textContent = "";
  try {
    const cleanupResponse = await fetch("/api/spy/cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...pending.scope,
        delete_media: pending.deleteMedia,
        confirmation: "XOA"
      })
    });
    const responseText = await cleanupResponse.text();
    let cleanupResult;
    try {
      cleanupResult = JSON.parse(responseText);
    } catch (parseError) {
      throw new Error(`HTTP ${cleanupResponse.status}: phản hồi không phải JSON`);
    }
    if (!cleanupResponse.ok) {
      throw new Error(cleanupResult.detail || `HTTP ${cleanupResponse.status}`);
    }
    const result = cleanupResult.data;
    state.pendingCleanup = null;
    closeModal();
    showToast(`Đã xóa ${result.pages_deleted} Page và ${result.posts_deleted} bài`, "success");
    if (result.backup_path) appendLog(`Backup trước khi dọn: ${result.backup_path}`, "OK");
    if (pending.deleteMedia) {
      appendLog(
        `Media: đã xóa ${result.media_deleted}, bỏ qua ${result.media_skipped}, lỗi ${result.media_failed}`,
        result.media_failed ? "WARNING" : "OK"
      );
    }
    document.getElementById("spy-delete-media").checked = false;
    await loadSpyPages();
    await fetchStats();
  } catch (error) {
    console.error("Cleanup execution failed", error);
    errorBox.textContent = `Không thể dọn kho: ${error.message || "lỗi không xác định"}`;
    showToast(errorBox.textContent, "error");
    confirmButton.disabled = false;
    confirmButton.textContent = "Thử lại";
  }
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
  const media = source
    ? `<div class="spy-media-lightbox spy-preview-lightbox">${source.kind === "video"
      ? `<video src="${escapeHtml(source.src)}" controls preload="metadata" playsinline autoplay muted data-spy-autoplay onerror="this.parentElement.innerHTML='<div class=&quot;spy-preview-media-error&quot;>Không thể tải video xem trước.</div>'"></video>`
      : `<img src="${escapeHtml(source.src)}" alt="Thumbnail bài viết" referrerpolicy="no-referrer" onerror="this.parentElement.innerHTML='<div class=&quot;spy-preview-media-error&quot;>Không thể tải thumbnail.</div>'">`
    }${isVideoPost && source.kind !== "video" ? '<span class="spy-preview-video-indicator"><span>▶</span> Video</span>' : ""}</div>`
    : `<div class="spy-detail-empty-media spy-preview-empty-media">
        <div class="spy-preview-empty-icon">${isVideoPost ? "🎥" : (post.post_type === "Ảnh" ? "🖼️" : "📄")}</div>
        <strong>Bài này chưa có thumbnail xem trước</strong>
        <span>Hãy quét lại Fanpage hoặc tải media để tạo preview nội bộ.</span>
      </div>`;
  return `<article class="spy-post-detail">
    <div class="spy-detail-summary">
      <div><span class="badge badge-teal">${escapeHtml(post.page_name || "Fanpage")}</span> <span class="badge badge-gray">${escapeHtml(post.date || "Không rõ ngày")}</span></div>
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
  const firstVideoIndex = media.findIndex(item => item.kind === "video");
  const gallery = media.length
    ? `<div class="spy-detail-gallery ${media.length === 1 ? "spy-detail-gallery-single" : ""}">${media.map((item, mediaIndex) => `
        <figure class="spy-detail-media">
          ${item.kind === "video"
            ? `<video src="${escapeHtml(item.url)}" controls preload="metadata" playsinline ${mediaIndex === firstVideoIndex ? "autoplay muted data-spy-autoplay" : ""}></video>`
            : `<img src="${escapeHtml(item.url)}" loading="lazy" alt="${escapeHtml(item.name || "Media bài viết")}">`}
          ${media.length > 1 ? `<figcaption>${escapeHtml(item.name || `Media ${Number(item.index) + 1}`)}</figcaption>` : ""}
        </figure>`).join("")}</div>`
    : `<div class="spy-detail-empty-media">📭 Không tìm thấy file media trong thư mục đã tải.</div>`;
  return `<article class="spy-post-detail">
    <div class="spy-detail-summary">
      <div><span class="badge badge-teal">${escapeHtml(post.page_name || "Fanpage")}</span> <span class="badge badge-gray">${escapeHtml(post.date || "Không rõ ngày")}</span></div>
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
      ${gallery}
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

function playSpyModalVideo() {
  const video = document.querySelector("#generic-modal.active video[data-spy-autoplay]");
  if (!video) return;
  video.muted = true;
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

  state.spyPosts.forEach((post, index) => {
    const card = document.createElement("div");
    card.className = "post-card";

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
          ${spyDownloadStatusMarkup(post)}
        </div>
        <div class="spy-post-actions">
          <button class="btn btn-teal btn-sm" onclick="downloadSpyPost(${Number(post.id)})" ${post.url ? "" : "disabled"}>⬇ Download</button>
          <button class="btn btn-danger btn-sm" onclick="deleteSpyPost(${Number(post.id)})">🗑 Xóa</button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderSpyPostsTable() {
  const tbody = document.getElementById("spy-posts-tbody");
  tbody.innerHTML = "";

  state.spyPosts.forEach((post, i) => {
    const totalEngagement = (Number(post.engagement) || 0) + (Number(post.comments) || 0) + (Number(post.shares) || 0);
    const tr = document.createElement("tr");
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
      <td style="padding: 10px 12px;">${spyDownloadStatusMarkup(post)} ${spyRatingListMarkup(post)}</td>
      <td style="padding: 10px 12px;"><div class="spy-post-actions"><button class="btn btn-teal btn-sm" onclick="downloadSpyPost(${Number(post.id)})" ${post.url ? "" : "disabled"}>Download</button><button class="btn btn-danger btn-sm" onclick="deleteSpyPost(${Number(post.id)})">Xóa</button></div></td>
    `;
    tbody.appendChild(tr);
  });
  updateSortIndicators("spy", state.spySort);
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
    downloaded: { label: "Đã tải", badge: "badge-green", icon: "✓" }
  };
  const item = states[status] || states.not_downloaded;
  const error = status === "failed" && post.download_error
    ? ` title="${escapeHtml(post.download_error)}"`
    : "";
  return `<span class="badge ${item.badge}"${error}>${item.icon} ${item.label}</span>`;
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
  const urls = [...new Set(posts.map(post => safeFacebookPostUrl(post.url)).filter(Boolean))];
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
        max_threads: parseInt(document.getElementById("dl-threads")?.value) || 4,
        use_accounts: Boolean(document.getElementById("dl-use-accounts")?.checked)
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Không thể bắt đầu tải");
    const startedUrls = new Set(urls);
    state.spyPosts.forEach(post => {
      if (startedUrls.has(safeFacebookPostUrl(post.url))) {
        post.download_status = "downloading";
        post.download_error = "";
        post.downloaded = 0;
      }
    });
    renderSpyPostsGrid();
    renderSpyPostsTable();
    syncSpyPostSelectionUi();
    showToast(`Đã bắt đầu Download ${urls.length} bài`, "success");
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

async function deleteSpyPosts(rowIds, { deleteMedia = false, requireConfirmation = true } = {}) {
  const uniqueIds = [...new Set(rowIds.map(Number).filter(value => value > 0))];
  if (!uniqueIds.length) {
    showToast("Chưa chọn bài cần xóa", "warning");
    return false;
  }
  if (requireConfirmation && !confirm(`Xóa ${uniqueIds.length} bài khỏi Kho Dữ Liệu? Media đã tải sẽ được giữ nguyên.`)) return false;
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
        ? (mediaFailed ? `Đã xóa ${deleted} bài; ${mediaFailed} thư mục media không thể xóa` : `Đã xóa ${deleted} bài và ${mediaDeleted} thư mục media`)
        : `Đã xóa ${deleted} bài; media vẫn được giữ`,
      mediaFailed ? "warning" : "success"
    );
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
  deleteSpyPosts([...state.selectedSpyPostIds]);
}

// ─── Tab 4: Accounts Manager ────────────────────────────────────────────────

async function loadAccounts() {
  try {
    const res = await fetch("/api/accounts/");
    const json = await res.json();
    if (json.status === "success") {
      state.accounts = json.data;
      renderAccountsTable();
    }
  } catch (e) {}
}

function renderAccountsTable() {
  const tbody = document.getElementById("accounts-tbody");
  tbody.innerHTML = "";
  const exportButton = document.getElementById("btn-export-profile");
  if (exportButton) exportButton.disabled = state.accounts.length === 0;
  const cleanupButton = document.getElementById("btn-cleanup-profiles");
  if (cleanupButton) cleanupButton.disabled = state.accounts.length === 0;

  state.accounts.forEach((acc, index) => {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    tr.innerHTML = `
      <td style="padding: 12px 14px;" title="ID hệ thống: ${Number(acc.id) || 0}">#${index + 1}</td>
      <td style="padding: 12px 14px; font-weight: 700;">${escapeHtml(acc.label || 'Account')}</td>
      <td style="padding: 12px 14px;">${escapeHtml(acc.username || '—')}</td>
      <td style="padding: 12px 14px;"><span class="badge ${acc.is_active ? 'badge-green' : 'badge-red'}">${acc.is_active ? 'Active / Live' : 'Disabled'}</span></td>
      <td style="padding: 12px 14px; text-align: right;">
        <div style="display:flex; justify-content:flex-end; gap:6px; flex-wrap:wrap;">
          <button class="btn btn-teal btn-sm" onclick="launchAccountChrome(${Number(acc.id) || 0})">🌐 Mở Chrome</button>
          <button class="btn btn-secondary btn-sm" onclick="closeAccountChrome(${Number(acc.id) || 0})">✕ Đóng Chrome</button>
          <button class="btn btn-secondary btn-sm" onclick="openAccountEditor(${Number(acc.id) || 0})">✏️ Sửa</button>
          <button class="btn btn-danger btn-sm" onclick="deleteAccount(${Number(acc.id) || 0})">🗑 Xóa</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
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
    showToast(res.ok ? `Đã mở Chrome Profile #${displayId}` : (json.detail || "Không thể mở Chrome"), res.ok ? "success" : "error");
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
  try {
    const res = await fetch("/api/accounts/profile/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId })
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
  showToast("Đang Export thông tin account và phiên Chrome. File ZIP chứa dữ liệu đăng nhập, hãy bảo quản cẩn thận...", "info");
  try {
    const res = await fetch("/api/accounts/profile/export-all", {method: "POST"});
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
  try {
    await fetch("/api/accounts/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId })
    });
    loadAccounts();
    fetchStats();
    showToast("Đã xóa tài khoản", "info");
  } catch (e) {}
}

function getAccountDisplayId(accId) {
  const index = state.accounts.findIndex(item => Number(item.id) === Number(accId));
  return index >= 0 ? index + 1 : Number(accId) || 0;
}

function openAccountEditor(accId = null) {
  const account = accId === null
    ? null
    : state.accounts.find(item => Number(item.id) === Number(accId));
  if (accId !== null && !account) {
    showToast("Không tìm thấy tài khoản cần sửa", "error");
    return;
  }

  const isEditing = Boolean(account);
  const secretHint = isEditing ? "Để trống nếu muốn giữ nguyên" : "Tùy chọn";
  openModal(isEditing ? "✏️ Chỉnh Sửa Tài Khoản Facebook" : "➕ Thêm Tài Khoản Facebook", `
    <div class="account-editor-form">
      <label>
        <span>Tên gợi nhớ (Label)</span>
        <input type="text" id="acc-label" value="${escapeHtml(account?.label || '')}" placeholder="VD: Nick chính, Profile 1">
      </label>
      <label>
        <span>Username / UID</span>
        <input type="text" id="acc-username" value="${escapeHtml(account?.username || '')}" placeholder="UID hoặc email đăng nhập">
      </label>
      <label>
        <span>Mật khẩu</span>
        <input type="password" id="acc-password" placeholder="${secretHint}">
        ${isEditing && account.has_password ? '<small>Đang có mật khẩu đã lưu.</small>' : ''}
      </label>
      <label>
        <span>Mã bí mật 2FA</span>
        <input type="text" id="acc-2fa" placeholder="${secretHint}">
        ${isEditing && account.has_2fa ? '<small>Đang có mã 2FA đã lưu.</small>' : ''}
      </label>
      <label>
        <span>Cookie Facebook</span>
        <textarea id="acc-cookie" rows="3" placeholder="${secretHint}"></textarea>
        ${isEditing && account.has_cookie ? '<small>Đang có cookie đã lưu.</small>' : ''}
      </label>
      <label class="custom-checkbox account-active-toggle">
        <input type="checkbox" id="acc-active" ${account === null || account.is_active ? 'checked' : ''}>
        <span>Kích hoạt tài khoản</span>
      </label>
    </div>
  `, `
    <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
    <button class="btn btn-primary" onclick="submitAccount(${account ? Number(account.id) : 'null'})">${isEditing ? 'Lưu Thay Đổi' : 'Lưu Tài Khoản'}</button>
  `);
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
  initWebSocket();
  initTabs();
  initCollapsiblePanels();
  initAutoDownloadOption();
  initDownloader();
  initScraper();
  loadConfig();
  loadAppVersion();
  fetchStats();
  setInterval(pollFavoriteScanStatus, 2500);

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
          <input type="number" id="setting-max-threads" value="${state.config.max_threads || 4}" min="1" max="16">
        </div>
        <div>
          <label class="custom-checkbox">
            <input type="checkbox" id="setting-auto-open" ${state.config.auto_open_folder ? 'checked' : ''}>
            <span>Tự động mở thư mục sau khi tải xong</span>
          </label>
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

  // Refresh Spy Button
  document.getElementById("btn-refresh-spy").addEventListener("click", loadSpyPosts);
  document.getElementById("spy-mode").addEventListener("change", applySpyModeSelection);
  document.getElementById("btn-delete-spy-pages").addEventListener("click", () => cleanupSpyRepository(false));
  document.getElementById("btn-clear-spy").addEventListener("click", () => cleanupSpyRepository(true));
  document.getElementById("spy-select-all-posts").addEventListener("change", event => selectAllSpyPosts(event.target.checked));
  document.getElementById("btn-download-spy-posts").addEventListener("click", downloadSelectedSpyPosts);
  document.getElementById("btn-delete-spy-posts").addEventListener("click", deleteSelectedSpyPosts);
  document.getElementById("spy-select-all-pages").addEventListener("change", (event) => {
    const checked = event.target.checked;
    document.querySelectorAll("#spy-pages-container input[type='checkbox']").forEach(input => {
      input.checked = checked;
    });
    state.selectedPageNames = checked ? state.scrapedPages.map(page => page.page_name) : [];
    state.selectedPageUrls = checked ? state.scrapedPages.map(page => page.page_url) : [];
    loadSpyPosts();
  });


  // View toggle in Spy
  document.getElementById("btn-view-grid").addEventListener("click", () => {
    document.getElementById("spy-posts-grid").style.display = "grid";
    document.getElementById("spy-posts-table-wrap").style.display = "none";
    observeSpyLazyMedia();
  });

  document.getElementById("btn-view-table").addEventListener("click", () => {
    document.getElementById("spy-posts-grid").style.display = "none";
    document.getElementById("spy-posts-table-wrap").style.display = "block";
    observeSpyLazyMedia();
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
  const threads = parseInt(document.getElementById("setting-max-threads").value) || 4;
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
