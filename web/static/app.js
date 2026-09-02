/**
 * Tinix FB Studio - Main WebUI Application Controller
 */

const state = {
  activeTab: "tab-downloader",
  wsConnected: false,
  scrapedPages: [],
  selectedPageNames: [],
  selectedPageUrls: [],
  spyPosts: [],
  posterItems: [],
  pendingSchedule: [],
  posterJobs: [],
  accounts: [],
  scrapeAccounts: [],
  favoritePages: [],
  favoriteScanWasRunning: false,
  config: {},
  pendingCleanup: null
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function encodeInlineArg(value) {
  return encodeURIComponent(String(value ?? "")).replace(/'/g, "%27");
}

async function persistPosterSchedule() {
  if (!state.pendingSchedule.length) {
    showToast("Không có lịch để lưu", "warning");
    return;
  }
  try {
    const response = await fetch("/api/poster/persist-schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schedules: state.pendingSchedule })
    });
    const result = await response.json();
    if (!response.ok) {
      showToast(result.detail || "Không thể lưu lịch đăng", "error");
      return;
    }
    closeModal();
    state.pendingSchedule = [];
    showToast(`Đã lưu ${result.inserted} công việc; bỏ qua ${result.skipped} bản trùng.`, "success");
  } catch (error) {
    showToast("Lỗi kết nối khi lưu lịch đăng", "error");
  }
}

// ─── WebSocket Connection ───────────────────────────────────────────────────

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  const ws = new WebSocket(wsUrl);

  const badge = document.getElementById("ws-badge");

  ws.onopen = () => {
    state.wsConnected = true;
    badge.className = "badge badge-green";
    badge.textContent = "🟢 Realtime Connected";
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
    badge.className = "badge badge-amber";
    badge.textContent = "🟡 Đang kết nối lại...";
    setTimeout(initWebSocket, 3000);
  };

  ws.onerror = () => {
    badge.className = "badge badge-red";
    badge.textContent = "🔴 Mất kết nối WS";
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
      showToast("Tải xuống hoàn tất!", "success");
    }
  }
  if (data.task === "poster") {
    const summary = document.getElementById("poster-queue-summary");
    if (summary) summary.textContent = `Đang xử lý ${data.current}/${data.total}`;
    if (data.total > 0 && data.current >= data.total) loadPosterJobs();
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
    "tab-poster": "🚀 Đăng Tự Động — Social Poster Studio",
    "tab-accounts": "👥 Quản Lý Tài Khoản & Chrome Profiles"
  };

  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const target = item.getAttribute("data-tab");
      navItems.forEach(n => n.classList.remove("active"));
      panels.forEach(p => p.classList.remove("active"));

      item.classList.add("active");
      document.getElementById(target).classList.add("active");
      title.textContent = tabTitles[target] || "Tinix FB Studio";
      state.activeTab = target;

      if (target === "tab-spy") loadSpyPages();
      if (target === "tab-scraper") {
        loadScrapeAccounts();
        loadFavoritePages();
      }
      if (target === "tab-accounts") loadAccounts();
      if (target === "tab-poster") loadPosterJobs();
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
    }
  } catch (e) {}
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
    const pageUrl = document.getElementById("scrape-url").value.trim();
    if (!pageUrl) {
      showToast("Vui lòng nhập URL Fanpage!", "warning");
      return;
    }

    const mode = document.getElementById("scrape-mode").value;
    const limit = parseInt(document.getElementById("scrape-limit").value) || 50;
    const accountId = parseInt(document.getElementById("scrape-account").value) || null;

    try {
      const res = await fetch("/api/scrape/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page_url: pageUrl, mode: mode, limit: limit, account_id: accountId })
      });
      const json = await res.json();
      if (res.ok) {
        showToast("Đã bắt đầu quét Fanpage!", "success");
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
  document.getElementById("btn-scan-selected-favorites").addEventListener("click", () => {
    const ids = Array.from(document.querySelectorAll(".favorite-page-check:checked"))
      .map(input => Number(input.value)).filter(Boolean);
    if (!ids.length) {
      showToast("Hãy chọn ít nhất một Fanpage", "warning");
      return;
    }
    scanFavoritePages(ids);
  });
  document.getElementById("btn-scan-all-favorites").addEventListener("click", () => scanFavoritePages([]));
  document.getElementById("favorite-select-all").addEventListener("change", event => {
    document.querySelectorAll(".favorite-page-check").forEach(input => {
      input.checked = event.target.checked;
    });
  });
}

async function loadScrapeAccounts() {
  try {
    const res = await fetch("/api/accounts/");
    const json = await res.json();
    state.scrapeAccounts = res.ok ? (json.data || []) : [];
    const select = document.getElementById("scrape-account");
    const current = select.value;
    select.innerHTML = `<option value="">Profile mặc định</option>` + state.scrapeAccounts.map(account =>
      `<option value="${Number(account.id)}">${escapeHtml(account.label || account.username || `Account #${account.id}`)}</option>`
    ).join("");
    select.value = current;
  } catch (e) {}
}

async function loadFavoritePages() {
  try {
    const res = await fetch("/api/scrape/favorites");
    const json = await res.json();
    if (res.ok) {
      state.favoritePages = json.data || [];
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

function renderFavoritePages() {
  const tbody = document.getElementById("favorite-pages-tbody");
  const summary = document.getElementById("favorite-scan-summary");
  summary.textContent = `${state.favoritePages.length} Fanpage`;
  if (!state.favoritePages.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted" style="padding:28px; text-align:center;">Chưa có Fanpage yêu thích</td></tr>`;
    return;
  }
  tbody.innerHTML = state.favoritePages.map(page => {
    const label = page.page_name || page.page_url.replace(/^https?:\/\/(www\.)?facebook\.com\//, "");
    const account = page.account_label || "Profile mặc định";
    const lastScan = page.last_successful_scan_at || "Chưa quét";
    const error = page.last_error ? `<div class="text-muted" title="${escapeHtml(page.last_error)}" style="max-width:210px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(page.last_error)}</div>` : "";
    return `
      <tr style="border-bottom:1px solid var(--border-subtle);">
        <td style="padding:10px;"><input class="favorite-page-check" type="checkbox" value="${Number(page.id)}" checked></td>
        <td style="padding:10px;">
          <div style="font-weight:700;">⭐ ${escapeHtml(label)}</div>
          <div class="text-muted" style="font-size:11.5px; max-width:310px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(page.page_url)}">${escapeHtml(page.page_url)}</div>
        </td>
        <td style="padding:10px;">
          <div>${escapeHtml(account)}</div>
          <div class="text-muted">Tối đa ${Number(page.scan_limit) || 100} bài</div>
        </td>
        <td style="padding:10px;">${escapeHtml(lastScan)}</td>
        <td style="padding:10px;">
          <span class="badge ${favoriteStatusClass(page.last_status)}">${escapeHtml(page.last_status)}</span>
          <div style="margin-top:4px;">+${Number(page.last_new_posts_count) || 0} bài mới</div>
          ${error}
        </td>
        <td style="padding:10px; text-align:right;">
          <div style="display:flex; justify-content:flex-end; gap:5px; flex-wrap:wrap;">
            <button class="btn btn-teal btn-sm" onclick="scanFavoritePages([${Number(page.id)}])">Quét mới</button>
            <button class="btn btn-secondary btn-sm" onclick="editFavoritePage(${Number(page.id)})">Sửa</button>
            <button class="btn btn-secondary btn-sm" onclick="resetFavoritePage(${Number(page.id)})">Đặt lại mốc</button>
            <button class="btn btn-danger btn-sm" onclick="deleteFavoritePageUi(${Number(page.id)})">Bỏ</button>
          </div>
        </td>
      </tr>`;
  }).join("");
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
}

async function saveFavoriteFromForm() {
  const pageUrl = document.getElementById("scrape-url").value.trim();
  if (!pageUrl) {
    showToast("Hãy nhập URL Fanpage trước", "warning");
    return;
  }
  try {
    await saveFavorite({
      page_url: pageUrl,
      scan_limit: parseInt(document.getElementById("scrape-limit").value) || 100,
      account_id: parseInt(document.getElementById("scrape-account").value) || null
    });
    showToast("Đã lưu Fanpage yêu thích", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function scanFavoritePages(ids) {
  try {
    const res = await fetch("/api/scrape/favorites/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ favorite_ids: ids })
    });
    const json = await res.json();
    if (!res.ok) {
      showToast(json.detail || "Không thể bắt đầu quét", "error");
      return;
    }
    state.favoriteScanWasRunning = true;
    showToast(`Đã xếp hàng ${json.queued} Fanpage`, "success");
    loadFavoritePages();
  } catch (e) {
    showToast("Lỗi kết nối khi bắt đầu hàng đợi", "error");
  }
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
  if (!confirm("Đặt lại mốc sẽ khiến lần quét sau tạo một mốc mới. Tiếp tục?")) return;
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

function editFavoritePage(favoriteId) {
  const page = state.favoritePages.find(item => Number(item.id) === Number(favoriteId));
  if (!page) return;
  const accountOptions = `<option value="">Profile mặc định</option>` + state.scrapeAccounts.map(account =>
    `<option value="${Number(account.id)}" ${Number(page.account_id) === Number(account.id) ? "selected" : ""}>${escapeHtml(account.label || account.username || `Account #${account.id}`)}</option>`
  ).join("");
  openModal("Sửa Fanpage yêu thích", `
    <div style="display:flex; flex-direction:column; gap:12px;">
      <div><label style="font-weight:700; display:block; margin-bottom:4px;">Fanpage</label><input id="favorite-edit-name" value="${escapeHtml(page.page_name || "")}" placeholder="Tên gợi nhớ"></div>
      <div><label style="font-weight:700; display:block; margin-bottom:4px;">Account Chrome</label><select id="favorite-edit-account">${accountOptions}</select></div>
      <div><label style="font-weight:700; display:block; margin-bottom:4px;">Giới hạn bài</label><input type="number" id="favorite-edit-limit" min="5" max="2000" value="${Number(page.scan_limit) || 100}"></div>
    </div>`, `
      <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary" onclick="saveFavoriteEdit(${Number(page.id)})">Lưu</button>`);
}

async function saveFavoriteEdit(favoriteId) {
  const page = state.favoritePages.find(item => Number(item.id) === Number(favoriteId));
  if (!page) return;
  try {
    await saveFavorite({
      page_url: page.page_url,
      page_name: document.getElementById("favorite-edit-name").value.trim(),
      account_id: parseInt(document.getElementById("favorite-edit-account").value) || null,
      scan_limit: parseInt(document.getElementById("favorite-edit-limit").value) || 100
    });
    closeModal();
    showToast("Đã cập nhật Fanpage", "success");
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
    if (data.is_running) {
      state.favoriteScanWasRunning = true;
      summary.textContent = `Đang quét ${data.queue_completed + 1}/${data.queue_total} · +${data.new_posts} bài`;
    } else if (state.favoriteScanWasRunning) {
      state.favoriteScanWasRunning = false;
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
      loadSpyPosts();
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
    document.getElementById("spy-posts-grid").innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px;" class="text-muted">Chưa chọn page nào để hiển thị</div>`;
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
        query: query
      })
    });
    const json = await res.json();
    if (json.status === "success") {
      state.spyPosts = json.data;
      renderSpyPostsGrid();
      renderSpyPostsTable();
    }
  } catch (e) {}
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

function renderSpyPostsGrid() {
  const container = document.getElementById("spy-posts-grid");
  container.innerHTML = "";

  if (!state.spyPosts.length) {
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px;" class="text-muted">Không tìm thấy bài viết phù hợp</div>`;
    return;
  }

  state.spyPosts.forEach(post => {
    const card = document.createElement("div");
    card.className = "post-card";
    const thumbUrl = post.url ? `/media-preview?path=${encodeURIComponent(post.url)}` : "";
    const totalEngage = (post.engagement || 0) + (post.comments || 0) + (post.shares || 0);
    const safePostUrl = post.post_id ? `https://facebook.com/${encodeURIComponent(String(post.post_id))}` : "#";

    card.innerHTML = `
      <div class="post-card-thumb" onclick="window.open('${safePostUrl}', '_blank')">
        ${post.post_type === 'Video' ? '<span style="font-size: 32px;">🎥</span>' : '<span style="font-size: 32px;">📄</span>'}
      </div>
      <div class="post-card-body">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span class="badge badge-teal">${escapeHtml(post.page_name)}</span>
          <span class="badge badge-gray">${escapeHtml(post.date || 'Hôm nay')}</span>
        </div>
        <div class="post-card-caption">${post.caption ? escapeHtml(post.caption) : '<i>(Không có nội dung văn bản)</i>'}</div>
        <div class="post-card-meta">
          <span>👍 ${post.engagement || 0} | 💬 ${post.comments || 0} | 🔁 ${post.shares || 0}</span>
          <span class="badge ${post.downloaded ? 'badge-green' : 'badge-amber'}">${post.downloaded ? 'Đã tải' : 'Chưa tải'}</span>
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
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    tr.innerHTML = `
      <td style="padding: 10px 12px;">${i + 1}</td>
      <td style="padding: 10px 12px; font-weight: 600;">${escapeHtml(post.page_name)}</td>
      <td style="padding: 10px 12px;">${escapeHtml(post.date || '—')}</td>
      <td style="padding: 10px 12px;"><span class="badge badge-teal">${escapeHtml(post.post_type)}</span></td>
      <td style="padding: 10px 12px; font-weight: 700;">${post.engagement || 0}</td>
      <td style="padding: 10px 12px; max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(post.caption || '—')}</td>
      <td style="padding: 10px 12px;"><span class="badge ${post.downloaded ? 'badge-green' : 'badge-amber'}">${post.downloaded ? 'Đã tải' : 'Chưa tải'}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// ─── Tab 4: Poster Studio ───────────────────────────────────────────────────

function initPoster() {
  document.getElementById("btn-scan-poster-folder").addEventListener("click", async () => {
    const folder = document.getElementById("poster-folder").value.trim();
    if (!folder) {
      showToast("Vui lòng nhập đường dẫn thư mục!", "warning");
      return;
    }

    try {
      const res = await fetch("/api/poster/scan-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder_path: folder })
      });
      const json = await res.json();
      if (json.status === "success") {
        state.posterItems = json.data;
        renderPosterItems();
        showToast(`Tìm thấy ${json.total} bài viết!`, "success");
      } else {
        showToast(json.detail || "Lỗi quét thư mục", "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", "error");
    }
  });

  // Set today as default start date
  const todayStr = new Date().toISOString().split("T")[0];
  document.getElementById("poster-start-date").value = todayStr;

  document.getElementById("btn-refresh-poster-jobs").addEventListener("click", loadPosterJobs);
  document.getElementById("btn-run-poster-jobs").addEventListener("click", runPosterQueue);
  document.getElementById("btn-retry-poster-jobs").addEventListener("click", retryPosterJobs);
  document.getElementById("btn-delete-poster-jobs").addEventListener("click", deletePosterJobs);
  document.getElementById("btn-stop-poster-jobs").addEventListener("click", stopPosterQueue);
  document.getElementById("poster-jobs-select-all").addEventListener("change", event => {
    document.querySelectorAll(".poster-job-check").forEach(box => { box.checked = event.target.checked; });
  });
}

function selectedPosterJobIds() {
  return Array.from(document.querySelectorAll(".poster-job-check:checked"))
    .map(box => Number(box.value)).filter(Boolean);
}

function posterStatusBadge(status) {
  if (status === "Scheduled" || status === "Success") return "badge-green";
  if (status === "Failed") return "badge-red";
  if (status === "Running") return "badge-teal";
  return "badge-amber";
}

async function loadPosterJobs() {
  try {
    const [jobsResponse, statusResponse] = await Promise.all([
      fetch("/api/poster/jobs"),
      fetch("/api/poster/queue-status")
    ]);
    const jobsResult = await jobsResponse.json();
    const statusResult = await statusResponse.json();
    state.posterJobs = jobsResult.data || [];
    const runner = statusResult.data || {};
    const counts = state.posterJobs.reduce((result, job) => {
      result[job.status] = (result[job.status] || 0) + 1;
      return result;
    }, {});
    const summary = document.getElementById("poster-queue-summary");
    summary.textContent = runner.is_running
      ? `Đang chạy ${runner.completed || 0}/${runner.total || 0}: ${runner.current || ""}`
      : `${state.posterJobs.length} job · Pending ${counts.Pending || 0} · Scheduled ${counts.Scheduled || 0} · Failed ${counts.Failed || 0}`;
    renderPosterJobs();
  } catch (error) {
    document.getElementById("poster-queue-summary").textContent = "Không thể tải hàng đợi";
  }
}

function renderPosterJobs() {
  const tbody = document.getElementById("poster-jobs-tbody");
  tbody.innerHTML = "";
  state.posterJobs.forEach(job => {
    const row = document.createElement("tr");
    row.style.borderBottom = "1px solid var(--border-subtle)";
    row.innerHTML = `
      <td style="padding:8px;"><input class="poster-job-check" type="checkbox" value="${Number(job.history_id) || 0}"></td>
      <td style="padding:8px; font-weight:600;">${escapeHtml(job.folder_name)}</td>
      <td style="padding:8px;">${escapeHtml(job.page_name)}</td>
      <td style="padding:8px; white-space:nowrap;">${escapeHtml(job.scheduled_time)}</td>
      <td style="padding:8px;"><span class="badge ${posterStatusBadge(job.status)}">${escapeHtml(job.status)}</span></td>
      <td style="padding:8px; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(job.error_log || '')}">${escapeHtml(job.error_log || "—")}</td>
    `;
    tbody.appendChild(row);
  });
}

async function runPosterQueue() {
  const ids = selectedPosterJobIds();
  const response = await fetch("/api/poster/queue-run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ history_ids: ids })
  });
  const result = await response.json();
  showToast(response.ok ? `Đã bắt đầu ${result.total} job` : (result.detail || "Không thể chạy hàng đợi"), response.ok ? "success" : "error");
  if (response.ok) loadPosterJobs();
}

async function stopPosterQueue() {
  await fetch("/api/poster/queue-stop", { method: "POST" });
  showToast("Đã gửi lệnh dừng hàng đợi", "warning");
  loadPosterJobs();
}

async function retryPosterJobs() {
  const ids = selectedPosterJobIds();
  if (!ids.length) return showToast("Chọn các job Failed cần retry", "warning");
  const response = await fetch("/api/poster/jobs/retry", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ history_ids: ids })
  });
  const result = await response.json();
  showToast(`Đã đưa ${result.changed || 0} job về Pending`, "success");
  loadPosterJobs();
}

async function deletePosterJobs() {
  const ids = selectedPosterJobIds();
  if (!ids.length) return showToast("Chọn các job Pending/Failed cần xóa", "warning");
  const response = await fetch("/api/poster/jobs/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ history_ids: ids })
  });
  const result = await response.json();
  showToast(response.ok ? `Đã xóa ${result.deleted || 0} job` : (result.detail || "Không thể xóa"), response.ok ? "success" : "error");
  loadPosterJobs();
}

function renderPosterItems() {
  const container = document.getElementById("poster-items-grid");
  container.innerHTML = "";

  state.posterItems.forEach(it => {
    const card = document.createElement("div");
    card.className = "post-card";
    const previewFile = it.media_files && it.media_files[0] ? it.media_files[0].rel_path : "";

    card.innerHTML = `
      <div class="post-card-thumb">
        ${previewFile ? `<img src="${escapeHtml(previewFile)}" alt="thumb">` : '<span style="font-size: 32px;">📁</span>'}
      </div>
      <div class="post-card-body">
        <div style="font-weight: 700; font-size: 13px;">${escapeHtml(it.folder_name)}</div>
        <div class="post-card-caption">${it.caption ? escapeHtml(it.caption) : '<i>(Chưa có caption. Bấm để sửa)</i>'}</div>
        <div class="post-card-meta">
          <span>🖼️ ${it.img_count} ảnh | 🎥 ${it.vid_count} video</span>
          <button class="btn btn-secondary btn-sm" onclick="openCaptionEditor('${encodeInlineArg(it.folder_path)}')">✏️ Sửa</button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function openCaptionEditor(encodedPath) {
  const fpath = decodeURIComponent(encodedPath);
  const it = state.posterItems.find(x => x.folder_path === fpath);
  if (!it) return;

  openModal("Chỉnh sửa Caption bài viết", `
    <div style="margin-bottom: 12px;"><b>Thư mục:</b> ${escapeHtml(it.folder_name)}</div>
    <textarea id="modal-caption-text" rows="8" style="width: 100%; font-size: 13px;">${escapeHtml(it.caption || '')}</textarea>
  `, `
    <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
    <button class="btn btn-primary" onclick="saveCaption('${encodeInlineArg(fpath)}')">Lưu Caption</button>
  `);
}

async function saveCaption(encodedPath) {
  const fpath = decodeURIComponent(encodedPath);
  const text = document.getElementById("modal-caption-text").value;

  try {
    const res = await fetch("/api/poster/update-caption", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: fpath, caption: text })
    });
    if (res.ok) {
      const it = state.posterItems.find(x => x.folder_path === fpath);
      if (it) it.caption = text;
      renderPosterItems();
      closeModal();
      showToast("Đã lưu caption!", "success");
    }
  } catch (e) {}
}

// ─── Tab 5: Accounts Manager ────────────────────────────────────────────────

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

  state.accounts.forEach(acc => {
    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-subtle)";
    tr.innerHTML = `
      <td style="padding: 12px 14px;">#${Number(acc.id) || 0}</td>
      <td style="padding: 12px 14px; font-weight: 700;">${escapeHtml(acc.label || 'Account')}</td>
      <td style="padding: 12px 14px;">${escapeHtml(acc.username || '—')}</td>
      <td style="padding: 12px 14px;"><span class="badge ${acc.is_active ? 'badge-green' : 'badge-red'}">${acc.is_active ? 'Active / Live' : 'Disabled'}</span></td>
      <td style="padding: 12px 14px; text-align: right;">
        <div style="display:flex; justify-content:flex-end; gap:6px; flex-wrap:wrap;">
          <button class="btn btn-teal btn-sm" onclick="launchAccountChrome(${Number(acc.id) || 0})">🌐 Mở Chrome</button>
          <button class="btn btn-secondary btn-sm" onclick="closeAccountChrome(${Number(acc.id) || 0})">✕ Đóng Chrome</button>
          <button class="btn btn-danger btn-sm" onclick="deleteAccount(${Number(acc.id) || 0})">🗑 Xóa</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function launchAccountChrome(accId) {
  showToast(`Đang mở Chrome Profile #${accId}...`, "info");
  try {
    const res = await fetch("/api/accounts/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: accId })
    });
    const json = await res.json();
    showToast(res.ok ? `Đã mở Chrome Profile #${accId}` : (json.detail || "Không thể mở Chrome"), res.ok ? "success" : "error");
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
  if (!confirm("Đóng Chrome của TẤT CẢ account trước khi Export. File ZIP sẽ chứa toàn bộ phiên đăng nhập. Tiếp tục?")) return;
  try {
    const res = await fetch("/api/accounts/profile/export-all", {method: "POST"});
    const json = await res.json();
    showToast(res.ok ? `Đã Export ${json.accounts_exported} profile: ${json.archive_path}` : (json.detail || "Không thể Export profiles"), res.ok ? "success" : "error");
  } catch (e) {
    showToast("Lỗi kết nối khi Export profiles", "error");
  }
}

async function importAccountProfile() {
  const bundlePath = prompt("Nhập đường dẫn tuyệt đối tới file .tinix-profiles.zip (vẫn hỗ trợ thư mục .tinix-profile cũ):");
  if (!bundlePath) return;
  if (!confirm("Tinix sẽ tạo toàn bộ account Facebook và sao chép các Chrome profile từ file ZIP. Tiếp tục?")) return;
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
  if (!confirm(`Bạn có chắc muốn xóa tài khoản #${accId}?`)) return;
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

// ─── Modal & Toasts Helpers ─────────────────────────────────────────────────

function openModal(title, bodyHtml, footerHtml) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-footer").innerHTML = footerHtml;
  document.getElementById("generic-modal").classList.add("active");
}

function closeModal() {
  document.getElementById("generic-modal").classList.remove("active");
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
  initDownloader();
  initScraper();
  initPoster();
  loadConfig();
  fetchStats();
  setInterval(() => {
    if (state.activeTab === "tab-poster") loadPosterJobs();
  }, 4000);
  setInterval(pollFavoriteScanStatus, 2500);

  document.getElementById("btn-clear-logs").addEventListener("click", () => {
    document.getElementById("terminal-logs").innerHTML = "";
  });

  document.getElementById("btn-open-output-dir").addEventListener("click", async () => {
    await fetch("/api/system/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
  });

  document.getElementById("btn-close-modal").addEventListener("click", closeModal);
  document.getElementById("btn-close-all-chrome").addEventListener("click", closeAllAccountChrome);

  // Settings Modal
  document.getElementById("btn-settings-modal").addEventListener("click", () => {
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
    openModal("➕ Thêm Tài Khoản Facebook", `
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Tên gợi nhớ (Label):</label>
          <input type="text" id="acc-label" placeholder="VD: Nick chính, Profile 1">
        </div>
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Username / UID:</label>
          <input type="text" id="acc-username" placeholder="UID hoặc email đăng nhập">
        </div>
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Mật khẩu:</label>
          <input type="password" id="acc-password" placeholder="Mật khẩu (tùy chọn)">
        </div>
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Mã bí mật 2FA:</label>
          <input type="text" id="acc-2fa" placeholder="2FA Secret Key (nếu có)">
        </div>
        <div>
          <label style="font-weight: 700; font-size: 12.5px; margin-bottom: 4px; display: block;">Cookie Facebook:</label>
          <textarea id="acc-cookie" rows="3" placeholder="c_user=...; xs=..."></textarea>
        </div>
      </div>
    `, `
      <button class="btn btn-secondary" onclick="closeModal()">Hủy</button>
      <button class="btn btn-primary" onclick="submitAddAccount()">Lưu Tài Khoản</button>
    `);
  });

  document.getElementById("btn-import-profile").addEventListener("click", importAccountProfile);
  document.getElementById("btn-export-profile").addEventListener("click", exportAllAccountProfiles);

  // Refresh Spy Button
  document.getElementById("btn-refresh-spy").addEventListener("click", loadSpyPosts);
  document.getElementById("btn-delete-spy-pages").addEventListener("click", () => cleanupSpyRepository(false));
  document.getElementById("btn-clear-spy").addEventListener("click", () => cleanupSpyRepository(true));
  document.getElementById("spy-select-all-pages").addEventListener("change", (event) => {
    const checked = event.target.checked;
    document.querySelectorAll("#spy-pages-container input[type='checkbox']").forEach(input => {
      input.checked = checked;
    });
    state.selectedPageNames = checked ? state.scrapedPages.map(page => page.page_name) : [];
    state.selectedPageUrls = checked ? state.scrapedPages.map(page => page.page_url) : [];
    loadSpyPosts();
  });

  // Generate Schedule in Poster
  document.getElementById("btn-generate-schedule").addEventListener("click", async () => {
    if (!state.posterItems.length) {
      showToast("Vui lòng quét thư mục bài viết trước!", "warning");
      return;
    }
    const startDate = document.getElementById("poster-start-date").value || new Date().toISOString().split("T")[0];
    const timeSlotsRaw = document.getElementById("poster-time-slots").value || "08:00, 20:00";
    const timeSlots = timeSlotsRaw.split(",").map(t => t.trim()).filter(Boolean);

    // Fetch managed pages for target selection
    const resPages = await fetch("/api/accounts/managed-pages");
    const jsonPages = await resPages.json();
    const pages = jsonPages.data || [];

    if (!pages.length) {
      showToast("Chưa có fanpage quản lý nào! Hãy đồng bộ trong tab Tài khoản.", "warning");
      return;
    }

    try {
      const res = await fetch("/api/poster/generate-schedule", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: state.posterItems,
          target_pages: pages,
          start_date: startDate,
          time_slots: timeSlots
        })
      });
      const json = await res.json();
      if (res.ok) {
        state.pendingSchedule = json.data;
        let scheduleRows = json.data.map((j, idx) => `
          <tr style="border-bottom: 1px solid var(--border-subtle);">
            <td style="padding: 8px 10px;">${idx + 1}</td>
            <td style="padding: 8px 10px; font-weight: 700;">${escapeHtml(j.folder_name)}</td>
            <td style="padding: 8px 10px;"><span class="badge badge-teal">${escapeHtml(j.target_page)}</span></td>
            <td style="padding: 8px 10px; font-weight: 600;">${escapeHtml(j.scheduled_time)}</td>
            <td style="padding: 8px 10px;"><span class="badge badge-amber">${j.status}</span></td>
          </tr>
        `).join("");

        openModal("📅 Lịch Đăng Bài Dự Kiến (" + json.total_jobs + " bài)", `
          <div style="max-height: 380px; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 12.5px;">
              <thead>
                <tr style="background: var(--teal-dark); color: #FFFFFF;">
                  <th style="padding: 8px 10px;">STT</th>
                  <th style="padding: 8px 10px;">Folder</th>
                  <th style="padding: 8px 10px;">Fanpage</th>
                  <th style="padding: 8px 10px;">Thời gian đăng</th>
                  <th style="padding: 8px 10px;">Trạng thái</th>
                </tr>
              </thead>
              <tbody>${scheduleRows}</tbody>
            </table>
          </div>
        `, `
          <button class="btn btn-secondary" onclick="closeModal()">Đóng</button>
          <button class="btn btn-primary" onclick="persistPosterSchedule()">Xác Nhận Đặt Lịch</button>
        `);
      } else {
        showToast(json.detail || "Lỗi tạo lịch", "error");
      }
    } catch (e) {
      showToast("Lỗi kết nối", "error");
    }
  });

  // View toggle in Spy
  document.getElementById("btn-view-grid").addEventListener("click", () => {
    document.getElementById("spy-posts-grid").style.display = "grid";
    document.getElementById("spy-posts-table-wrap").style.display = "none";
  });

  document.getElementById("btn-view-table").addEventListener("click", () => {
    document.getElementById("spy-posts-grid").style.display = "none";
    document.getElementById("spy-posts-table-wrap").style.display = "block";
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
        body: JSON.stringify({ page_names: state.selectedPageNames })
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
      state.config.output_dir = outDir;
      state.config.max_threads = threads;
      state.config.auto_open_folder = autoOpen;
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

async function submitAddAccount() {
  const label = document.getElementById("acc-label").value.trim();
  const username = document.getElementById("acc-username").value.trim();
  const password = document.getElementById("acc-password").value.trim();
  const secret2fa = document.getElementById("acc-2fa").value.trim();
  const cookie = document.getElementById("acc-cookie").value.trim();

  if (!label && !username) {
    showToast("Vui lòng nhập Tên gợi nhớ hoặc Username!", "warning");
    return;
  }

  try {
    const res = await fetch("/api/accounts/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: label,
        username: username,
        password: password,
        secret_2fa: secret2fa,
        cookie: cookie
      })
    });
    if (res.ok) {
      closeModal();
      loadAccounts();
      fetchStats();
      showToast("Đã thêm tài khoản mới!", "success");
    }
  } catch (e) {}
}
