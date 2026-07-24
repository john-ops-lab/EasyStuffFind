"use strict";

const state = {
  token: "",
  locations: [],
  tree: null,
  items: [],
  history: [],
  selectedLocationId: null,
  selectedItems: new Set(),
  currentTab: "locations",
  movingItemIds: [],
  searchTimer: null,
};

const elements = Object.fromEntries(
  [
    "auth-dialog", "auth-form", "auth-error", "token-input", "token-settings",
    "health-state", "global-search", "location-panel", "location-tree",
    "location-summary", "tree-toggle", "close-tree", "mobile-back", "view-title",
    "view-path", "items-view", "history-view", "item-list", "history-list",
    "add-item", "edit-location", "selection-bar", "selection-count",
    "clear-selection", "bulk-move", "drawer-backdrop", "edit-drawer",
    "item-form", "item-id", "item-name", "item-aliases", "item-location",
    "item-note", "item-photo", "photo-hint", "drawer-title", "drawer-subtitle",
    "close-drawer", "cancel-drawer", "save-item", "location-dialog",
    "location-form", "location-id", "location-name", "location-parent",
    "location-parent-field", "location-dialog-title", "location-dialog-help",
    "location-error", "delete-location", "add-location", "move-dialog",
    "move-form", "move-title", "move-help", "move-location", "move-error", "toast",
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
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${state.token}`);
  if (options.body && !(options.body instanceof Blob) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/v1${path}`, { ...options, headers });
  let body = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    body = await response.json();
  }
  if (!response.ok) {
    if (response.status === 401) {
      state.token = "";
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
  elements["auth-error"].textContent = errorMessage;
  elements["auth-error"].hidden = !errorMessage;
  elements["token-input"].value = "";
  if (!elements["auth-dialog"].open) elements["auth-dialog"].showModal();
  requestAnimationFrame(() => elements["token-input"].focus());
}

async function authenticate(token) {
  state.token = token.trim();
  try {
    await api("/locations");
  } catch (error) {
    state.token = "";
    throw error;
  }
}

function flattenTree(nodes, depth = 0, result = []) {
  for (const node of nodes) {
    result.push({ ...node, depth });
    flattenTree(node.children || [], depth + 1, result);
  }
  return result;
}

function renderTree() {
  if (!state.tree) return;
  const rootSelected = state.selectedLocationId === null;
  const allRows = flattenTree(state.tree.children || []);
  const root = `
    <button class="tree-row ${rootSelected ? "selected" : ""}" data-location-id="">
      ${icons.home}<span class="tree-name">全屋</span>
      <span class="tree-count">${state.tree.item_count || 0}</span>
    </button>`;
  const rows = allRows.map((node) => `
    <div class="tree-node" style="--depth:${node.depth}">
      <button class="tree-row ${state.selectedLocationId === node.id ? "selected" : ""}" data-location-id="${node.id}">
        ${icons.folder}<span class="tree-name">${escapeHtml(node.name)}</span>
        <span class="tree-count">${node.item_count || 0}</span>
      </button>
    </div>`).join("");
  elements["location-tree"].innerHTML = root + rows;
  elements["location-summary"].textContent = `${allRows.length} 个位置`;
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
      ? `<img src="${escapeHtml(item.photo_url)}" alt="${escapeHtml(item.name)}的位置照片" loading="lazy">`
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
  renderTree();
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

async function refreshVisibleItems() {
  const query = elements["global-search"].value.trim();
  if (query) {
    await searchItems(query);
  } else {
    await loadItems();
  }
}

async function bootstrap() {
  await Promise.all([loadStructure(), loadItems(), loadHistory()]);
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
  elements["items-view"].hidden = history;
  elements["history-view"].hidden = !history;
  if (tab === "items") state.selectedLocationId = null;
  if (!history) {
    elements["global-search"].value = "";
    updateHeading();
  }
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
    await Promise.all([refreshVisibleItems(), loadHistory()]);
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
    await Promise.all([refreshVisibleItems(), loadHistory()]);
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
    await Promise.all([refreshVisibleItems(), loadHistory()]);
    showToast(`已删除：${item.name}`);
  } catch (error) {
    showToast(error.message, "error");
  }
}

elements["auth-form"].addEventListener("submit", async (event) => {
  event.preventDefault();
  elements["auth-error"].hidden = true;
  try {
    await authenticate(elements["token-input"].value);
    elements["auth-dialog"].close();
    await bootstrap();
  } catch (error) {
    openAuth(error.message);
  }
});

elements["token-settings"].addEventListener("click", () => openAuth());
elements["location-tree"].addEventListener("click", (event) => {
  const row = event.target.closest("[data-location-id]");
  if (!row) return;
  const locationId = row.dataset.locationId ? Number(row.dataset.locationId) : null;
  selectLocation(locationId).catch((error) => showToast(error.message, "error"));
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
    searchItems(event.target.value).catch((error) => showToast(error.message, "error"));
  }, 260);
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
if (state.token) {
  bootstrap().catch((error) => {
    if (error.status !== 401) showToast(error.message, "error");
  });
} else {
  openAuth();
}
