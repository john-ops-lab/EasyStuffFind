"use strict";

const COLLAPSED_LOCATIONS_STORAGE_KEY = "easystufffind.collapsedLocationIds";
const PHOTO_ZOOM_MIN = 0.5;
const PHOTO_ZOOM_MAX = 3;
const PHOTO_ZOOM_STEP = 0.25;

function loadCollapsedLocationIds() {
  try {
    const stored = JSON.parse(
      window.localStorage.getItem(COLLAPSED_LOCATIONS_STORAGE_KEY) || "[]"
    );
    return new Set(
      Array.isArray(stored)
        ? stored.filter((value) => Number.isInteger(value) && value > 0)
        : []
    );
  } catch {
    return new Set();
  }
}

function saveCollapsedLocationIds() {
  try {
    window.localStorage.setItem(
      COLLAPSED_LOCATIONS_STORAGE_KEY,
      JSON.stringify([...state.collapsedLocationIds])
    );
  } catch {
    // 浏览器禁用本地存储时仍保留当前页面内的折叠功能。
  }
}

const state = {
  currentUser: null,
  locations: [],
  tree: null,
  items: [],
  allItems: [],
  history: [],
  selectedLocationId: null,
  selectedItems: new Set(),
  collapsedLocationIds: loadCollapsedLocationIds(),
  mindMapExpandedLocationIds: new Set(),
  mindMapInitialized: false,
  detailItemId: null,
  currentTab: "locations",
  movingItemIds: [],
  searchTimer: null,
  photoZoom: 1,
  photoFitWidth: 0,
  photoFitHeight: 0,
  restoreTicket: null,
};

const elements = Object.fromEntries(
  [
    "auth-dialog", "auth-form", "auth-error", "login-username", "login-password",
    "account-settings", "account-dialog", "account-username", "password-form",
    "current-password", "new-password", "confirm-password", "password-error", "logout",
    "health-state", "global-search", "location-panel", "location-tree",
    "location-summary", "tree-toggle", "close-tree", "mobile-back", "view-title",
    "view-path", "items-view", "history-view", "mindmap-view", "mindmap-canvas",
    "backup-view", "backup-config-form", "backup-frequency", "backup-time",
    "backup-weekday-field", "backup-weekday", "backup-monthday-field", "backup-monthday",
    "backup-retention", "backup-cloud-enabled", "backup-cloud-fields", "backup-provider",
    "backup-region", "backup-endpoint", "backup-bucket", "backup-prefix",
    "backup-access-key", "backup-secret", "backup-secret-state", "backup-config-error",
    "backup-test-cloud", "backup-now", "backup-upload", "backup-upload-input",
    "backup-refresh", "backup-list", "restore-dialog", "restore-form",
    "restore-backup-id", "restore-password", "restore-help", "restore-step-one",
    "restore-step-two", "restore-summary", "restore-error", "restore-authorize",
    "restore-execute",
    "item-list", "history-list",
    "add-item", "edit-location", "selection-bar", "selection-count",
    "clear-selection", "bulk-move", "drawer-backdrop", "edit-drawer",
    "item-form", "item-id", "item-name", "item-aliases", "item-location",
    "item-note", "item-photo", "photo-hint", "drawer-title", "drawer-subtitle",
    "close-drawer", "cancel-drawer", "save-item", "location-dialog",
    "location-form", "location-id", "location-name", "location-parent",
    "location-parent-field", "location-dialog-title", "location-dialog-help",
    "location-error", "delete-location", "add-location", "move-dialog",
    "move-form", "move-title", "move-help", "move-location", "move-error",
    "item-detail-dialog", "item-detail-name", "item-detail-location",
    "item-detail-content", "item-detail-edit", "photo-viewer-dialog",
    "photo-viewer-title", "photo-viewer-image", "photo-zoom-out",
    "photo-zoom-reset", "photo-zoom-in", "toast",
  ].map((id) => [id, document.getElementById(id)])
);

const icons = {
  folder: '<svg class="tree-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg>',
  home: '<svg class="tree-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/></svg>',
  photo: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-5-5L5 20"/></svg>',
  box: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="m4 7 8 4 8-4v10l-8 4-8-4V7Z"/></svg>',
  edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4.2-1 10.9-10.9a2.1 2.1 0 0 0-3-3L5.2 16 4 20Z"/><path d="m14.5 6.5 3 3"/></svg>',
  move: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v18M3 12h18"/><path d="m8 7 4-4 4 4M8 17l4 4 4-4M7 8l-4 4 4 4M17 8l4 4-4 4"/></svg>',
  trash: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/></svg>',
  more: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>',
  chevron: '<svg class="tree-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>',
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatFullTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function showToast(message, type = "success") {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", type === "error");
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 3200);
}

async function api(path, options = {}) {
  const { skipAuthPrompt = false, ...requestOptions } = options;
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof Blob) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/v1${path}`, {
    ...requestOptions,
    headers,
    credentials: "same-origin",
  });
  let body = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    body = await response.json();
  }
  if (!response.ok) {
    if (response.status === 401 && !skipAuthPrompt) {
      state.currentUser = null;
      openAuth();
    }
    const error = new Error(body?.error?.message || `请求失败（${response.status}）`);
    error.status = response.status;
    error.details = body?.error?.details || {};
    throw error;
  }
  return body;
}

async function verifyHealth() {
  try {
    const response = await fetch("/health");
    const body = await response.json();
    const healthy = response.ok && body.status === "ok";
    elements["health-state"].classList.toggle("offline", !healthy);
    elements["health-state"].title = healthy ? `服务正常 · v${body.version}` : "服务异常";
  } catch {
    elements["health-state"].classList.add("offline");
    elements["health-state"].title = "无法连接服务";
  }
}

function openAuth(errorMessage = "") {
  if (elements["account-dialog"].open) elements["account-dialog"].close();
  elements["auth-error"].textContent = errorMessage;
  elements["auth-error"].hidden = !errorMessage;
  elements["login-username"].value = state.currentUser?.username || "admin";
  elements["login-password"].value = "";
  if (!elements["auth-dialog"].open) elements["auth-dialog"].showModal();
  requestAnimationFrame(() => elements["login-password"].focus());
}

async function authenticate(username, password) {
  const result = await api("/web-auth/login", {
    method: "POST",
    body: JSON.stringify({ username: username.trim(), password }),
    skipAuthPrompt: true,
  });
  state.currentUser = result.user;
}

async function restoreWebSession() {
  try {
    const result = await api("/web-auth/me", { skipAuthPrompt: true });
    state.currentUser = result.user;
    return true;
  } catch (error) {
    if (error.status !== 401) throw error;
    state.currentUser = null;
    return false;
  }
}

function flattenTree(nodes, depth = 0, result = []) {
  for (const node of nodes) {
    result.push({ ...node, depth });
    flattenTree(node.children || [], depth + 1, result);
  }
  return result;
}

function renderTreeNode(node, depth = 0) {
  const children = node.children || [];
  const hasChildren = children.length > 0;
  const collapsed = hasChildren && state.collapsedLocationIds.has(node.id);
  const selected = state.selectedLocationId === node.id;
  const branchId = `tree-branch-${node.id}`;
  const disclosure = hasChildren
    ? `<button
        class="tree-disclosure"
        type="button"
        data-tree-toggle-id="${node.id}"
        aria-label="${collapsed ? "展开" : "折叠"}“${escapeHtml(node.name)}”下级位置"
        aria-expanded="${collapsed ? "false" : "true"}"
        aria-controls="${branchId}"
      >${icons.chevron}</button>`
    : '<span class="tree-disclosure-placeholder" aria-hidden="true"></span>';
  const childRows = hasChildren
    ? `<div class="tree-children" id="${branchId}" role="group" ${collapsed ? "hidden" : ""}>
        ${children.map((child) => renderTreeNode(child, depth + 1)).join("")}
      </div>`
    : "";

  return `
    <div class="tree-node" role="treeitem" ${hasChildren ? `aria-expanded="${collapsed ? "false" : "true"}"` : ""}>
      <div class="tree-node-row ${selected ? "selected" : ""}" style="--depth:${depth}">
        ${disclosure}
        <button class="tree-row" type="button" data-location-id="${node.id}">
          ${icons.folder}<span class="tree-name">${escapeHtml(node.name)}</span>
          <span class="tree-count">${node.item_count || 0}</span>
        </button>
      </div>
      ${childRows}
    </div>`;
}

function renderTree() {
  if (!state.tree) return;
  const rootSelected = state.selectedLocationId === null;
  const allRows = flattenTree(state.tree.children || []);
  const root = `
    <div class="tree-node-row tree-root-row ${rootSelected ? "selected" : ""}" style="--depth:0">
      <span class="tree-disclosure-placeholder" aria-hidden="true"></span>
      <button class="tree-row" type="button" data-location-id="">
        ${icons.home}<span class="tree-name">全屋</span>
        <span class="tree-count">${state.tree.item_count || 0}</span>
      </button>
    </div>`;
  const rows = (state.tree.children || []).map((node) => renderTreeNode(node)).join("");
  elements["location-tree"].innerHTML = root + rows;
  elements["location-summary"].textContent = `${allRows.length} 个位置`;
}

function itemsAtLocation(locationId) {
  return state.allItems.filter((item) => item.location.id === locationId);
}

function initializeMindMap() {
  if (state.mindMapInitialized || !state.tree) return;
  for (const node of state.tree.children || []) {
    state.mindMapExpandedLocationIds.add(node.id);
  }
  state.mindMapInitialized = true;
}

function renderMindMapItem(item) {
  return `
    <button class="mindmap-node mindmap-item-node" type="button" data-mind-item-id="${item.id}">
      ${icons.box}
      <span>
        <strong>${escapeHtml(item.name)}</strong>
        <small>${escapeHtml(item.location.path)}</small>
      </span>
    </button>`;
}

function renderMindMapLocation(node) {
  const locationItems = itemsAtLocation(node.id);
  const children = node.children || [];
  const hasContents = children.length > 0 || locationItems.length > 0;
  const expanded = hasContents && state.mindMapExpandedLocationIds.has(node.id);
  const contents = expanded
    ? `
      <div class="mindmap-children" role="group">
        ${children.map((child) => renderMindMapLocation(child)).join("")}
        ${locationItems.map((item) => renderMindMapItem(item)).join("")}
      </div>`
    : "";

  return `
    <div class="mindmap-branch">
      <button
        class="mindmap-node mindmap-location-node ${expanded ? "expanded" : ""}"
        type="button"
        data-mind-location-id="${node.id}"
        aria-expanded="${expanded ? "true" : "false"}"
        ${hasContents ? "" : "disabled"}
      >
        ${icons.folder}
        <span>
          <strong>${escapeHtml(node.name)}</strong>
          <small>${node.item_count || 0} 件物品</small>
        </span>
        ${hasContents ? icons.chevron : ""}
      </button>
      ${contents}
    </div>`;
}

function renderMindMap() {
  if (!state.tree) return;
  initializeMindMap();
  const roots = state.tree.children || [];
  elements["mindmap-canvas"].innerHTML = `
    <div class="mindmap-root-branch">
      <div class="mindmap-node mindmap-home-node">
        ${icons.home}
        <span><strong>全屋</strong><small>${state.allItems.length} 件物品</small></span>
      </div>
      <div class="mindmap-children mindmap-root-children" role="tree">
        ${roots.map((node) => renderMindMapLocation(node)).join("")}
      </div>
    </div>`;
}

function renderLocationOptions(select, includeRoot = false) {
  const options = [];
  if (includeRoot) options.push('<option value="">全屋（顶层）</option>');
  for (const location of state.locations) {
    options.push(`<option value="${location.id}">${escapeHtml(location.path)}</option>`);
  }
  select.innerHTML = options.join("");
}

function currentLocation() {
  return state.locations.find((location) => location.id === state.selectedLocationId) || null;
}

function updateHeading(searchLabel = "") {
  const selected = currentLocation();
  if (searchLabel) {
    elements["view-title"].textContent = `“${searchLabel}”的结果`;
    elements["view-path"].textContent = `${state.items.length} 个匹配物品`;
  } else if (state.currentTab === "items") {
    elements["view-title"].textContent = "全部物品";
    elements["view-path"].textContent = "按最近更新时间排列";
  } else if (selected) {
    elements["view-title"].textContent = selected.name;
    elements["view-path"].textContent = selected.path;
  } else {
    elements["view-title"].textContent = "全屋物品";
    elements["view-path"].textContent = "所有位置";
  }
  elements["edit-location"].disabled = !selected;
}

function renderItems() {
  if (!state.items.length) {
    elements["item-list"].innerHTML = `
      <div class="empty-state">
        <div>
          ${icons.box}
          <h3>这里还没有物品</h3>
          <p>点击“记录物品”添加第一件，或换一个关键词继续搜索。</p>
        </div>
      </div>`;
    updateSelectionBar();
    return;
  }
  elements["item-list"].innerHTML = state.items.map((item) => {
    const selected = state.selectedItems.has(item.id);
    const aliases = item.aliases.length ? item.aliases.join("、") : "暂无别名";
    const photo = item.photo_url
      ? `<button class="item-photo-button" type="button" data-action="view-photo" aria-label="放大查看 ${escapeHtml(item.name)} 的照片">
          <img src="${escapeHtml(item.photo_url)}" alt="${escapeHtml(item.name)}的位置照片" loading="lazy">
        </button>`
      : icons.photo;
    return `
      <article class="item-row" data-item-id="${item.id}">
        <input class="item-check" type="checkbox" aria-label="选择 ${escapeHtml(item.name)}" ${selected ? "checked" : ""}>
        <div class="item-identity">
          <span class="item-name">${escapeHtml(item.name)}</span>
          <span class="item-alias">${escapeHtml(aliases)}</span>
        </div>
        <div class="item-location" title="${escapeHtml(item.location.path)}">${escapeHtml(item.location.path)}</div>
        <time class="item-time" datetime="${escapeHtml(item.updated_at)}">${formatTime(item.updated_at)}</time>
        <div class="item-photo">${photo}</div>
        <div class="row-actions">
          <button class="row-action" data-action="edit" aria-label="编辑 ${escapeHtml(item.name)}">${icons.edit}<span>编辑</span></button>
          <button class="row-action" data-action="move" aria-label="移动 ${escapeHtml(item.name)}">${icons.move}<span>移动</span></button>
          <button class="row-action danger" data-action="delete" aria-label="删除 ${escapeHtml(item.name)}">${icons.trash}<span>删除</span></button>
        </div>
      </article>`;
  }).join("");
  updateSelectionBar();
}

function updateSelectionBar() {
  const count = state.selectedItems.size;
  elements["selection-count"].textContent = String(count);
  elements["selection-bar"].hidden = count === 0;
}

function renderHistory() {
  if (!state.history.length) {
    elements["history-list"].innerHTML = `
      <div class="empty-state">
        <div>${icons.move}<h3>还没有位置变更</h3><p>移动物品后，原位置和新位置会记录在这里。</p></div>
      </div>`;
    return;
  }
  elements["history-list"].innerHTML = state.history.map((entry) => `
    <article class="history-entry">
      <span class="history-marker"></span>
      <div class="history-copy">
        <strong>${escapeHtml(entry.item_name)}</strong>
        <div class="history-path">
          ${escapeHtml(entry.old_location_path || "首次记录")}
          <span class="history-arrow"> → </span>
          ${escapeHtml(entry.new_location_path)}
        </div>
      </div>
      <time class="history-time" datetime="${escapeHtml(entry.changed_at)}">${formatTime(entry.changed_at)}</time>
    </article>`).join("");
}

async function loadStructure() {
  const [treeBody, locationsBody] = await Promise.all([
    api("/locations/tree"),
    api("/locations"),
  ]);
  state.tree = treeBody.tree;
  state.locations = locationsBody.locations;
  const validLocationIds = new Set(state.locations.map((location) => location.id));
  state.collapsedLocationIds = new Set(
    [...state.collapsedLocationIds].filter((locationId) => validLocationIds.has(locationId))
  );
  saveCollapsedLocationIds();
  state.mindMapExpandedLocationIds = new Set(
    [...state.mindMapExpandedLocationIds].filter((locationId) => validLocationIds.has(locationId))
  );
  renderTree();
  renderMindMap();
  renderLocationOptions(elements["item-location"]);
  renderLocationOptions(elements["location-parent"], true);
  renderLocationOptions(elements["move-location"]);
}

async function loadItems() {
  const path = state.currentTab === "locations" && state.selectedLocationId
    ? `/locations/${state.selectedLocationId}/items`
    : "/items";
  const body = await api(path);
  state.items = body.items;
  state.selectedItems.clear();
  updateHeading();
  renderItems();
}

async function loadHistory() {
  const body = await api("/history?limit=200");
  state.history = body.history;
  renderHistory();
}

async function loadMindMapItems() {
  const body = await api("/items");
  state.allItems = body.items;
  renderMindMap();
}

async function refreshVisibleItems() {
  const query = elements["global-search"].value.trim();
  if (query) {
    await searchItems(query);
  } else {
    await loadItems();
  }
}

async function bootstrap() {
  await loadStructure();
  await Promise.all([loadItems(), loadHistory(), loadMindMapItems()]);
  await verifyHealth();
}

async function selectLocation(locationId) {
  state.currentTab = "locations";
  state.selectedLocationId = locationId;
  elements["global-search"].value = "";
  setActiveTab("locations");
  renderTree();
  await loadItems();
  elements["location-panel"].classList.remove("open");
}

function setActiveTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  const history = tab === "history";
  const mindmap = tab === "mindmap";
  const backup = tab === "backup";
  elements["items-view"].hidden = history || mindmap || backup;
  elements["history-view"].hidden = !history;
  elements["mindmap-view"].hidden = !mindmap;
  elements["backup-view"].hidden = !backup;
  if (tab === "items") state.selectedLocationId = null;
  if (!history && !mindmap && !backup) {
    elements["global-search"].value = "";
    updateHeading();
  }
  if (mindmap) renderMindMap();
}

function formatBytes(value) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function updateBackupScheduleFields() {
  const frequency = elements["backup-frequency"].value;
  elements["backup-weekday-field"].hidden = frequency !== "weekly";
  elements["backup-monthday-field"].hidden = frequency !== "monthly";
  elements["backup-cloud-fields"].hidden = !elements["backup-cloud-enabled"].checked;
}

async function loadBackupConfig() {
  const { config } = await api("/backups/config");
  elements["backup-frequency"].value = config.frequency;
  elements["backup-time"].value = config.time;
  elements["backup-weekday"].value = String(config.weekday);
  elements["backup-monthday"].value = String(config.monthday);
  elements["backup-retention"].value = String(config.retention_days);
  elements["backup-cloud-enabled"].checked = config.cloud_enabled;
  elements["backup-provider"].value = config.provider;
  elements["backup-region"].value = config.region;
  elements["backup-endpoint"].value = config.endpoint_url;
  elements["backup-bucket"].value = config.bucket;
  elements["backup-prefix"].value = config.prefix;
  elements["backup-access-key"].value = "";
  elements["backup-access-key"].placeholder = config.access_key_id_masked || "AccessKey ID";
  elements["backup-secret"].value = "";
  elements["backup-secret-state"].textContent = config.secret_configured ? "已配置，留空保留" : "尚未配置";
  updateBackupScheduleFields();
}

async function loadBackups() {
  const result = await api("/backups");
  elements["backup-list"].innerHTML = result.backups.length
    ? result.backups.map((backup) => `
      <div class="backup-entry">
        <div><strong>${escapeHtml(formatFullTime(backup.created_at))}</strong><small>${escapeHtml(backup.reason === "scheduled" ? "自动备份" : backup.reason === "pre_restore" ? "恢复前紧急备份" : "手工备份")} · ${formatBytes(backup.bytes)}</small></div>
        <div class="backup-entry-actions">
          <a class="text-button" href="/api/v1/backups/${encodeURIComponent(backup.id)}/download">下载</a>
          <button class="danger-text-button" type="button" data-restore-id="${escapeHtml(backup.id)}">恢复</button>
        </div>
      </div>`).join("")
    : '<div class="empty-state"><strong>还没有备份</strong><p>点击“立即备份”创建第一份。</p></div>';
}

async function loadBackupView() {
  await Promise.all([loadBackupConfig(), loadBackups()]);
}

function openRestore(backupId) {
  state.restoreTicket = null;
  elements["restore-form"].reset();
  elements["restore-backup-id"].value = backupId;
  elements["restore-step-one"].hidden = false;
  elements["restore-step-two"].hidden = true;
  elements["restore-authorize"].hidden = false;
  elements["restore-execute"].hidden = true;
  elements["restore-error"].hidden = true;
  elements["restore-help"].textContent = "第一步：输入当前登录密码";
  elements["restore-dialog"].showModal();
  requestAnimationFrame(() => elements["restore-password"].focus());
}

async function searchItems(query) {
  const cleaned = query.trim();
  if (!cleaned) {
    await loadItems();
    return;
  }
  const result = await api(`/items/search?q=${encodeURIComponent(cleaned)}`);
  state.items = result.status === "unique" ? [result.item] : result.candidates;
  state.selectedItems.clear();
  updateHeading(cleaned);
  renderItems();
}

function openDrawer(item = null) {
  elements["item-form"].reset();
  elements["item-id"].value = item?.id || "";
  elements["drawer-title"].textContent = item ? "编辑物品" : "记录物品";
  elements["drawer-subtitle"].textContent = item
    ? `最近更新于 ${formatTime(item.updated_at)}`
    : "保存后可立即通过 API 查询";
  elements["item-name"].value = item?.name || "";
  elements["item-aliases"].value = item?.aliases?.join(", ") || "";
  const preferredLocation = item?.location?.id || state.selectedLocationId || state.locations[0]?.id;
  if (preferredLocation) elements["item-location"].value = String(preferredLocation);
  elements["item-note"].value = item?.note || "";
  elements["photo-hint"].textContent = item?.photo
    ? "已有照片；选择新文件会替换"
    : "JPEG、PNG、WebP 或 GIF";
  elements["drawer-backdrop"].hidden = false;
  document.body.classList.add("drawer-open");
  requestAnimationFrame(() => {
    elements["drawer-backdrop"].classList.add("open");
    elements["edit-drawer"].classList.add("open");
    elements["edit-drawer"].setAttribute("aria-hidden", "false");
    elements["item-name"].focus();
  });
}

function openItemDetail(item) {
  state.detailItemId = item.id;
  elements["item-detail-name"].textContent = item.name;
  elements["item-detail-location"].textContent = item.location.path;
  const aliases = item.aliases.length ? item.aliases.join("、") : "无";
  const note = item.note || "无";
  const photo = item.photo_url
    ? `<button
        class="item-detail-photo-button"
        type="button"
        data-detail-photo-url="${escapeHtml(item.photo_url)}"
        aria-label="放大查看 ${escapeHtml(item.name)} 的照片"
      >
        <img class="item-detail-photo" src="${escapeHtml(item.photo_url)}" alt="${escapeHtml(item.name)}的位置照片">
        <span>点击放大</span>
      </button>`
    : `<div class="item-detail-photo-placeholder">${icons.photo}<span>暂无实景照片</span></div>`;
  elements["item-detail-content"].innerHTML = `
    ${photo}
    <dl class="item-detail-list">
      <div><dt>名称</dt><dd>${escapeHtml(item.name)}</dd></div>
      <div><dt>别名</dt><dd>${escapeHtml(aliases)}</dd></div>
      <div><dt>位置</dt><dd>${escapeHtml(item.location.path)}</dd></div>
      <div><dt>备注</dt><dd>${escapeHtml(note)}</dd></div>
      <div><dt>创建时间</dt><dd>${escapeHtml(formatFullTime(item.created_at))}</dd></div>
      <div><dt>更新时间</dt><dd>${escapeHtml(formatFullTime(item.updated_at))}</dd></div>
    </dl>`;
  elements["item-detail-dialog"].showModal();
}

function openPhotoViewer(url, itemName) {
  state.photoZoom = 1;
  state.photoFitWidth = 0;
  state.photoFitHeight = 0;
  elements["photo-viewer-title"].textContent = itemName;
  elements["photo-viewer-image"].src = url;
  elements["photo-viewer-image"].alt = `${itemName}的位置照片大图`;
  elements["photo-viewer-dialog"].showModal();
  if (elements["photo-viewer-image"].complete) {
    window.requestAnimationFrame(fitPhotoViewer);
  }
}

function fitPhotoViewer() {
  const image = elements["photo-viewer-image"];
  const stage = elements["photo-viewer-dialog"].querySelector(".photo-viewer-stage");
  if (!image.naturalWidth || !image.naturalHeight || !stage.clientWidth || !stage.clientHeight) return;

  const availableWidth = Math.max(1, stage.clientWidth - 40);
  const availableHeight = Math.max(1, stage.clientHeight - 40);
  let fitScale = Math.min(
    1,
    availableWidth / image.naturalWidth,
    availableHeight / image.naturalHeight
  );
  if (fitScale < 1) fitScale *= 0.92;
  state.photoFitWidth = Math.round(image.naturalWidth * fitScale);
  state.photoFitHeight = Math.round(image.naturalHeight * fitScale);
  applyPhotoZoom(false);
}

function applyPhotoZoom(center = true) {
  if (!state.photoFitWidth || !state.photoFitHeight) return;
  const image = elements["photo-viewer-image"];
  const stage = elements["photo-viewer-dialog"].querySelector(".photo-viewer-stage");
  image.style.width = `${Math.round(state.photoFitWidth * state.photoZoom)}px`;
  image.style.height = `${Math.round(state.photoFitHeight * state.photoZoom)}px`;
  elements["photo-zoom-reset"].textContent = `${Math.round(state.photoZoom * 100)}%`;
  elements["photo-zoom-out"].disabled = state.photoZoom <= PHOTO_ZOOM_MIN;
  elements["photo-zoom-in"].disabled = state.photoZoom >= PHOTO_ZOOM_MAX;

  if (center) {
    window.requestAnimationFrame(() => {
      stage.scrollTo({
        left: Math.max(0, (stage.scrollWidth - stage.clientWidth) / 2),
        top: Math.max(0, (stage.scrollHeight - stage.clientHeight) / 2),
      });
    });
  }
}

function changePhotoZoom(nextZoom) {
  state.photoZoom = Math.min(PHOTO_ZOOM_MAX, Math.max(PHOTO_ZOOM_MIN, nextZoom));
  applyPhotoZoom();
}

function closeDrawer() {
  elements["drawer-backdrop"].classList.remove("open");
  elements["edit-drawer"].classList.remove("open");
  elements["edit-drawer"].setAttribute("aria-hidden", "true");
  document.body.classList.remove("drawer-open");
  window.setTimeout(() => {
    elements["drawer-backdrop"].hidden = true;
  }, 220);
}

async function saveItem(event) {
  event.preventDefault();
  const id = Number(elements["item-id"].value) || null;
  const payload = {
    name: elements["item-name"].value.trim(),
    aliases: elements["item-aliases"].value
      .split(/[,，]/)
      .map((value) => value.trim())
      .filter(Boolean),
    location_id: Number(elements["item-location"].value),
    note: elements["item-note"].value.trim() || null,
  };
  elements["save-item"].disabled = true;
  try {
    const result = id
      ? await api(`/items/${id}`, { method: "PATCH", body: JSON.stringify(payload) })
      : await api("/items", { method: "POST", body: JSON.stringify(payload) });
    const item = result.item;
    const file = elements["item-photo"].files[0];
    if (file) {
      await api(`/items/${item.id}/photo`, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
      });
    }
    closeDrawer();
    await loadStructure();
    await Promise.all([refreshVisibleItems(), loadHistory(), loadMindMapItems()]);
    showToast(id ? `已更新：${item.name}` : `已记录：${item.name} → ${item.location.path}`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements["save-item"].disabled = false;
  }
}

function openLocationDialog(mode = "create") {
  const selected = currentLocation();
  elements["location-form"].reset();
  elements["location-error"].hidden = true;
  if (mode === "edit" && selected) {
    elements["location-dialog-title"].textContent = "编辑位置";
    elements["location-dialog-help"].textContent = selected.path;
    elements["location-id"].value = String(selected.id);
    elements["location-name"].value = selected.name;
    elements["location-parent-field"].hidden = true;
    elements["delete-location"].hidden = false;
  } else {
    elements["location-dialog-title"].textContent = "新建位置";
    elements["location-dialog-help"].textContent = selected
      ? `添加到 ${selected.path} 下`
      : "添加一个顶层位置";
    elements["location-id"].value = "";
    elements["location-parent-field"].hidden = false;
    elements["location-parent"].value = selected ? String(selected.id) : "";
    elements["delete-location"].hidden = true;
  }
  elements["location-dialog"].showModal();
  requestAnimationFrame(() => elements["location-name"].focus());
}

async function saveLocation(event) {
  event.preventDefault();
  const id = Number(elements["location-id"].value) || null;
  const payload = id
    ? { name: elements["location-name"].value.trim() }
    : {
        name: elements["location-name"].value.trim(),
        parent_id: Number(elements["location-parent"].value) || null,
      };
  try {
    await api(id ? `/locations/${id}` : "/locations", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    elements["location-dialog"].close();
    await loadStructure();
    await refreshVisibleItems();
    showToast(id ? "位置名称已更新" : "位置已创建");
  } catch (error) {
    elements["location-error"].textContent = error.message;
    elements["location-error"].hidden = false;
  }
}

async function deleteCurrentLocation() {
  const selected = currentLocation();
  if (!selected || !window.confirm(`确定删除“${selected.path}”吗？`)) return;
  try {
    await api(`/locations/${selected.id}`, { method: "DELETE" });
    state.selectedLocationId = selected.parent_id;
    elements["location-dialog"].close();
    await loadStructure();
    await refreshVisibleItems();
    showToast("位置已删除");
  } catch (error) {
    const counts = error.details || {};
    const suffix = error.status === 409
      ? `（${counts.child_count || 0} 个子位置，${counts.item_count || 0} 件物品）`
      : "";
    elements["location-error"].textContent = error.message + suffix;
    elements["location-error"].hidden = false;
  }
}

function openMoveDialog(itemIds) {
  state.movingItemIds = itemIds;
  elements["move-form"].reset();
  elements["move-error"].hidden = true;
  elements["move-title"].textContent = itemIds.length > 1 ? `批量移动 ${itemIds.length} 件物品` : "移动物品";
  elements["move-help"].textContent = "每件物品的本次移动都会写入历史";
  const first = state.items.find((item) => item.id === itemIds[0]);
  if (first) elements["move-location"].value = String(first.location.id);
  elements["move-dialog"].showModal();
}

async function moveItems(event) {
  event.preventDefault();
  const locationId = Number(elements["move-location"].value);
  try {
    for (const itemId of state.movingItemIds) {
      await api(`/items/${itemId}/move`, {
        method: "POST",
        body: JSON.stringify({ location_id: locationId }),
      });
    }
    elements["move-dialog"].close();
    state.selectedItems.clear();
    await loadStructure();
    await Promise.all([refreshVisibleItems(), loadHistory(), loadMindMapItems()]);
    showToast(state.movingItemIds.length > 1 ? "批量移动完成" : "物品已移动");
  } catch (error) {
    elements["move-error"].textContent = error.message;
    elements["move-error"].hidden = false;
  }
}

async function deleteItem(item) {
  if (!window.confirm(`确定删除“${item.name}”吗？关联照片会一并删除。`)) return;
  try {
    await api(`/items/${item.id}`, { method: "DELETE" });
    await loadStructure();
    await Promise.all([refreshVisibleItems(), loadHistory(), loadMindMapItems()]);
    showToast(`已删除：${item.name}`);
  } catch (error) {
    showToast(error.message, "error");
  }
}

elements["auth-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["auth-error"].hidden = true;
  try {
    await authenticate(
      elements["login-username"].value,
      elements["login-password"].value,
    );
    elements["auth-dialog"].close();
    await bootstrap();
    if (!state.currentUser.password_changed) {
      showToast("当前仍使用默认密码，请在账户设置中尽快修改");
    }
  } catch (error) {
    openAuth(error.message);
  }
});

elements["account-settings"].addEventListener("click", () => {
  elements["password-form"].reset();
  elements["password-error"].hidden = true;
  elements["account-username"].textContent = state.currentUser?.username || "admin";
  elements["account-dialog"].showModal();
  requestAnimationFrame(() => elements["current-password"].focus());
});
elements["password-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["password-error"].hidden = true;
  const newPassword = elements["new-password"].value;
  if (newPassword !== elements["confirm-password"].value) {
    elements["password-error"].textContent = "两次输入的新密码不一致";
    elements["password-error"].hidden = false;
    return;
  }
  try {
    const result = await api("/web-auth/password", {
      method: "POST",
      body: JSON.stringify({
        current_password: elements["current-password"].value,
        new_password: newPassword,
      }),
    });
    state.currentUser = result.user;
    elements["account-dialog"].close();
    elements["password-form"].reset();
    showToast("密码已修改，其他旧登录状态已失效");
  } catch (error) {
    elements["password-error"].textContent = error.message;
    elements["password-error"].hidden = false;
  }
});
elements.logout.addEventListener("click", async () => {
  try {
    await api("/web-auth/logout", {
      method: "POST",
      skipAuthPrompt: true,
    });
  } finally {
    state.currentUser = null;
    elements["account-dialog"].close();
    openAuth();
  }
});
elements["location-tree"].addEventListener("click", (event) => {
  const disclosure = event.target.closest("[data-tree-toggle-id]");
  if (disclosure) {
    const locationId = Number(disclosure.dataset.treeToggleId);
    if (state.collapsedLocationIds.has(locationId)) {
      state.collapsedLocationIds.delete(locationId);
    } else {
      state.collapsedLocationIds.add(locationId);
    }
    saveCollapsedLocationIds();
    renderTree();
    return;
  }
  const row = event.target.closest("[data-location-id]");
  if (!row) return;
  const locationId = row.dataset.locationId ? Number(row.dataset.locationId) : null;
  selectLocation(locationId).catch((error) => showToast(error.message, "error"));
});
elements["mindmap-canvas"].addEventListener("click", (event) => {
  const itemButton = event.target.closest("[data-mind-item-id]");
  if (itemButton) {
    const item = state.allItems.find(
      (candidate) => candidate.id === Number(itemButton.dataset.mindItemId)
    );
    if (item) openItemDetail(item);
    return;
  }
  const locationButton = event.target.closest("[data-mind-location-id]");
  if (!locationButton || locationButton.disabled) return;
  const locationId = Number(locationButton.dataset.mindLocationId);
  if (state.mindMapExpandedLocationIds.has(locationId)) {
    state.mindMapExpandedLocationIds.delete(locationId);
  } else {
    state.mindMapExpandedLocationIds.add(locationId);
  }
  renderMindMap();
});
elements["item-detail-edit"].addEventListener("click", () => {
  const item = state.allItems.find((candidate) => candidate.id === state.detailItemId);
  if (!item) return;
  elements["item-detail-dialog"].close();
  openDrawer(item);
});
elements["item-detail-content"].addEventListener("click", (event) => {
  const photoButton = event.target.closest("[data-detail-photo-url]");
  if (!photoButton) return;
  const item = state.allItems.find((candidate) => candidate.id === state.detailItemId)
    || state.items.find((candidate) => candidate.id === state.detailItemId);
  if (item) openPhotoViewer(photoButton.dataset.detailPhotoUrl, item.name);
});
elements["photo-viewer-dialog"].addEventListener("click", (event) => {
  if (
    event.target === elements["photo-viewer-dialog"]
    || event.target.classList.contains("photo-viewer-stage")
    || event.target.classList.contains("photo-viewer-canvas")
  ) {
    elements["photo-viewer-dialog"].close();
  }
});
elements["photo-viewer-image"].addEventListener("load", fitPhotoViewer);
elements["photo-zoom-out"].addEventListener("click", () => {
  changePhotoZoom(state.photoZoom - PHOTO_ZOOM_STEP);
});
elements["photo-zoom-reset"].addEventListener("click", () => changePhotoZoom(1));
elements["photo-zoom-in"].addEventListener("click", () => {
  changePhotoZoom(state.photoZoom + PHOTO_ZOOM_STEP);
});
elements["photo-viewer-dialog"].addEventListener("close", () => {
  elements["photo-viewer-image"].removeAttribute("src");
  elements["photo-viewer-image"].removeAttribute("style");
  state.photoZoom = 1;
  state.photoFitWidth = 0;
  state.photoFitHeight = 0;
});
window.addEventListener("resize", () => {
  if (elements["photo-viewer-dialog"].open) fitPhotoViewer();
});
elements["tree-toggle"].addEventListener("click", () => elements["location-panel"].classList.add("open"));
elements["close-tree"].addEventListener("click", () => elements["location-panel"].classList.remove("open"));
elements["mobile-back"].addEventListener("click", () => elements["location-panel"].classList.add("open"));
elements["add-item"].addEventListener("click", () => openDrawer());
elements["close-drawer"].addEventListener("click", closeDrawer);
elements["cancel-drawer"].addEventListener("click", closeDrawer);
elements["drawer-backdrop"].addEventListener("click", closeDrawer);
elements["item-form"].addEventListener("submit", saveItem);
elements["add-location"].addEventListener("click", () => openLocationDialog("create"));
elements["edit-location"].addEventListener("click", () => openLocationDialog("edit"));
elements["location-form"].addEventListener("submit", saveLocation);
elements["delete-location"].addEventListener("click", deleteCurrentLocation);
elements["move-form"].addEventListener("submit", moveItems);
elements["clear-selection"].addEventListener("click", () => {
  state.selectedItems.clear();
  renderItems();
});
elements["bulk-move"].addEventListener("click", () => openMoveDialog([...state.selectedItems]));
elements["global-search"].addEventListener("input", (event) => {
  window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(() => {
    const query = event.target.value;
    if (["history", "mindmap", "backup"].includes(state.currentTab)) {
      setActiveTab("items");
      elements["global-search"].value = query;
    }
    searchItems(query).catch((error) => showToast(error.message, "error"));
  }, 260);
});
for (let day = 1; day <= 28; day += 1) {
  const option = document.createElement("option");
  option.value = String(day);
  option.textContent = `${day} 日`;
  elements["backup-monthday"].append(option);
}
elements["backup-frequency"].addEventListener("change", updateBackupScheduleFields);
elements["backup-cloud-enabled"].addEventListener("change", updateBackupScheduleFields);
elements["backup-config-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["backup-config-error"].hidden = true;
  try {
    const payload = {
      cloud_enabled: elements["backup-cloud-enabled"].checked,
      provider: elements["backup-provider"].value,
      endpoint_url: elements["backup-endpoint"].value.trim(),
      region: elements["backup-region"].value.trim(),
      bucket: elements["backup-bucket"].value.trim(),
      prefix: elements["backup-prefix"].value.trim(),
      access_key_id: elements["backup-access-key"].value.trim(),
      secret_access_key: elements["backup-secret"].value || null,
      clear_secret: false,
      frequency: elements["backup-frequency"].value,
      time: elements["backup-time"].value,
      weekday: Number(elements["backup-weekday"].value),
      monthday: Number(elements["backup-monthday"].value),
      retention_days: Number(elements["backup-retention"].value),
    };
    await api("/backups/config", { method: "PUT", body: JSON.stringify(payload) });
    await loadBackupConfig();
    showToast("备份设置已保存");
  } catch (error) {
    elements["backup-config-error"].textContent = error.message;
    elements["backup-config-error"].hidden = false;
  }
});
elements["backup-test-cloud"].addEventListener("click", async () => {
  try {
    await api("/backups/test-cloud", { method: "POST" });
    showToast("云对象存储连接正常");
  } catch (error) {
    showToast(error.message, "error");
  }
});
elements["backup-now"].addEventListener("click", async () => {
  elements["backup-now"].disabled = true;
  try {
    await api("/backups", {
      method: "POST",
      body: JSON.stringify({ upload_cloud: elements["backup-cloud-enabled"].checked }),
    });
    await loadBackups();
    showToast("备份已完成");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements["backup-now"].disabled = false;
  }
});
elements["backup-refresh"].addEventListener("click", () => {
  loadBackups().catch((error) => showToast(error.message, "error"));
});
elements["backup-upload"].addEventListener("click", () => elements["backup-upload-input"].click());
elements["backup-upload-input"].addEventListener("change", async () => {
  const file = elements["backup-upload-input"].files[0];
  if (!file) return;
  try {
    await api("/backups/upload", {
      method: "POST",
      headers: { "Content-Type": "application/zip" },
      body: file,
    });
    await loadBackups();
    showToast("备份文件已导入，可选择日期恢复");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements["backup-upload-input"].value = "";
  }
});
elements["backup-list"].addEventListener("click", (event) => {
  const button = event.target.closest("[data-restore-id]");
  if (button) openRestore(button.dataset.restoreId);
});
elements["restore-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["restore-error"].hidden = true;
  try {
    const result = await api("/backups/restore/authorize", {
      method: "POST",
      body: JSON.stringify({
        backup_id: elements["restore-backup-id"].value,
        password: elements["restore-password"].value,
      }),
    });
    state.restoreTicket = result.ticket;
    elements["restore-step-one"].hidden = true;
    elements["restore-step-two"].hidden = false;
    elements["restore-authorize"].hidden = true;
    elements["restore-execute"].hidden = false;
    elements["restore-help"].textContent = "第二步：核对后手工确认覆盖";
    elements["restore-summary"].textContent = `备份时间：${formatFullTime(result.summary.created_at)}，共 ${result.summary.files} 个文件。`;
  } catch (error) {
    elements["restore-error"].textContent = error.message;
    elements["restore-error"].hidden = false;
  }
});
elements["restore-execute"].addEventListener("click", async () => {
  elements["restore-execute"].disabled = true;
  try {
    const result = await api("/backups/restore/execute", {
      method: "POST",
      body: JSON.stringify({ ticket: state.restoreTicket, confirmation: "RESTORE" }),
    });
    elements["restore-dialog"].close();
    await bootstrap();
    await loadBackups();
    showToast(`恢复完成，紧急备份：${result.emergency_backup}`);
  } catch (error) {
    elements["restore-error"].textContent = error.message;
    elements["restore-error"].hidden = false;
  } finally {
    elements["restore-execute"].disabled = false;
  }
});
elements["item-list"].addEventListener("change", (event) => {
  if (!event.target.classList.contains("item-check")) return;
  const row = event.target.closest("[data-item-id]");
  const itemId = Number(row.dataset.itemId);
  if (event.target.checked) state.selectedItems.add(itemId);
  else state.selectedItems.delete(itemId);
  updateSelectionBar();
});
elements["item-list"].addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const row = action.closest("[data-item-id]");
  const item = state.items.find((candidate) => candidate.id === Number(row.dataset.itemId));
  if (!item) return;
  if (action.dataset.action === "view-photo" && item.photo_url) {
    openPhotoViewer(item.photo_url, item.name);
  }
  if (action.dataset.action === "edit") openDrawer(item);
  if (action.dataset.action === "move") openMoveDialog([item.id]);
  if (action.dataset.action === "delete") deleteItem(item);
});
document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", async () => {
    const tab = button.dataset.tab;
    setActiveTab(tab);
    try {
      if (tab === "history") await loadHistory();
      else if (tab === "mindmap") await loadMindMapItems();
      else if (tab === "backup") await loadBackupView();
      else await loadItems();
      if (tab === "locations" && window.innerWidth <= 760) {
        elements["location-panel"].classList.add("open");
      }
    } catch (error) {
      showToast(error.message, "error");
    }
  });
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById(button.dataset.closeDialog).close();
  });
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements["global-search"].focus();
  }
  if (event.key === "Escape" && elements["edit-drawer"].classList.contains("open")) {
    closeDrawer();
  }
});

verifyHealth();
restoreWebSession()
  .then(async (authenticated) => {
    if (!authenticated) {
      openAuth();
      return;
    }
    await bootstrap();
    if (!state.currentUser.password_changed) {
      showToast("当前仍使用默认密码，请在账户设置中尽快修改");
    }
  })
  .catch((error) => showToast(error.message, "error"));
