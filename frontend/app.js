const API = "/api";
const TOKEN_KEY = "it_slang_token";

const state = {
  terms: [],
  categories: [],
  activeCategory: null,
  search: "",
  editingId: null,
  viewingTerm: null,
  token: localStorage.getItem(TOKEN_KEY) || null,
  user: null,
};

const logState = {
  items: [],
  offset: 0,
  limit: 50,
  total: 0,
  actionsLoaded: false,
};

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");
const status = $("#status");
const searchInput = $("#search");
const categoriesNav = $("#categories");

function toast(message, type = "info", timeout = 3500) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 300);
  }, timeout);
}

function attachRipple() {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn");
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const ripple = document.createElement("span");
    ripple.className = "ripple";
    ripple.style.width = ripple.style.height = size + "px";
    ripple.style.left = (e.clientX - rect.left - size / 2) + "px";
    ripple.style.top = (e.clientY - rect.top - size / 2) + "px";
    btn.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  });
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers["X-Session-Token"] = state.token;

  const res = await fetch(API + path, { headers, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);

  if (res.status === 401 && state.token) {
    logout(true);
    throw new Error("Сессия истекла, войдите заново");
  }
  if (!res.ok) {
    const msg = data?.detail || `Ошибка ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function isAdmin() { return state.user?.role === "admin"; }
function isLoggedIn() { return !!state.user; }

function updateAuthUI() {
  const logged = isLoggedIn();
  const admin = isAdmin();
  // админ — может всё; обычный пользователь — только чтение и журнал
  $("#addBtn").classList.toggle("hidden", !admin);
  $("#usersBtn").classList.toggle("hidden", !admin);
  $("#logsBtn").classList.toggle("hidden", !logged);
  $("#loginBtn").classList.toggle("hidden", logged);
  $("#logoutBtn").classList.toggle("hidden", !logged);
  const badge = $("#profileBtn");
  if (logged) {
    badge.textContent = state.user.username + (admin ? " · админ" : "");
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function setSession(token, user) {
  state.token = token;
  state.user = user;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  updateAuthUI();
}

function logout(silent = false) {
  if (state.token) {
    fetch(API + "/auth/logout", {
      method: "POST",
      headers: { "X-Session-Token": state.token },
    }).catch(() => {});
  }
  setSession(null, null);
  if (!silent) toast("Вы вышли из аккаунта", "info");
  loadTerms();
}

async function restoreSession() {
  if (!state.token) return;
  try {
    const me = await fetch(API + "/auth/me", {
      headers: { "X-Session-Token": state.token },
    });
    if (!me.ok) throw new Error();
    state.user = await me.json();
  } catch {
    setSession(null, null);
  }
}

async function loadTerms() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.activeCategory) params.set("category", state.activeCategory);
  params.set("limit", "500");

  status.textContent = "Загружаю…";
  grid.innerHTML = "";
  try {
    const data = await api("/terms?" + params);
    state.terms = data.items;
    renderGrid();
    status.textContent = data.total === 0
      ? "Ничего не найдено."
      : `Найдено: ${data.total}`;
  } catch (e) {
    status.textContent = "Ошибка: " + e.message;
    toast(e.message, "error");
  }
}

async function loadCategories() {
  try {
    state.categories = await api("/categories");
    renderCategories();
    fillCategoryDatalist();
  } catch (e) { /* тихо */ }
}

function renderGrid() {
  grid.innerHTML = "";
  state.terms.forEach((t, i) => {
    const card = document.createElement("article");
    card.className = "card";
    card.style.setProperty("--i", Math.min(i, 30));

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = t.category;

    const h3 = document.createElement("h3");
    h3.textContent = t.term;

    const p = document.createElement("p");
    p.className = "short";
    p.textContent = t.definition;

    card.append(badge, h3, p);
    card.onclick = (e) => {
      if (e.target.closest(".btn")) return;
      openView(t);
    };

    // Кнопки управления — только у админа
    if (isAdmin()) {
      const actions = document.createElement("div");
      actions.className = "card-actions";

      const editBtn = document.createElement("button");
      editBtn.className = "btn ghost";
      editBtn.textContent = "✏ Изменить";
      editBtn.onclick = (e) => { e.stopPropagation(); openForm(t); };

      const delBtn = document.createElement("button");
      delBtn.className = "btn danger";
      delBtn.textContent = "🗑 Удалить";
      delBtn.onclick = (e) => { e.stopPropagation(); deleteTerm(t); };

      actions.append(editBtn, delBtn);
      card.appendChild(actions);
    }

    grid.appendChild(card);
  });
}

function renderCategories() {
  categoriesNav.innerHTML = "";
  const all = document.createElement("button");
  all.className = "cat-chip" + (state.activeCategory === null ? " active" : "");
  all.textContent = "Все";
  all.onclick = () => { state.activeCategory = null; loadTerms(); renderCategories(); };
  categoriesNav.appendChild(all);

  state.categories.forEach((c) => {
    const chip = document.createElement("button");
    chip.className = "cat-chip" + (state.activeCategory === c.name ? " active" : "");
    chip.innerHTML = `${escapeHtml(c.name)}<span class="count">${c.count}</span>`;
    chip.onclick = () => {
      state.activeCategory = c.name;
      loadTerms();
      renderCategories();
    };
    categoriesNav.appendChild(chip);
  });
}

function fillCategoryDatalist() {
  const dl = $("#catList");
  dl.innerHTML = "";
  state.categories.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.name;
    dl.appendChild(opt);
  });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (s) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[s]);
}

function openModal(id) { $(id).classList.remove("hidden"); }

function openView(term) {
  state.viewingTerm = term;
  $("#viewCategory").textContent = term.category;
  $("#viewTerm").textContent = term.term;
  $("#viewDefinition").textContent = term.definition;

  const wrap = $("#viewExampleWrap");
  if (term.example && term.example.trim()) {
    $("#viewExample").textContent = term.example;
    wrap.style.display = "";
  } else {
    wrap.style.display = "none";
  }
  $("#viewMeta").textContent = term.created_by
    ? `Добавил: ${term.created_by} · ${new Date(term.created_at).toLocaleString("ru")}`
    : "";
  openModal("#viewModal");
}

function openForm(term = null) {
  if (!isAdmin()) { toast("Только администратор может управлять терминами.", "warn"); return; }
  state.editingId = term ? term.id : null;
  $("#formTitle").textContent = term ? "Редактировать термин" : "Новый термин";
  const form = $("#termForm");
  form.reset();
  if (term) {
    form.term.value = term.term;
    form.category.value = term.category;
    form.definition.value = term.definition;
    form.example.value = term.example || "";
  }
  openModal("#formModal");
  form.term.focus();
}

async function submitForm(e) {
  e.preventDefault();
  const form = e.target;
  const payload = {
    term: form.term.value.trim(),
    category: form.category.value.trim(),
    definition: form.definition.value.trim(),
    example: form.example.value.trim(),
  };
  try {
    if (state.editingId) {
      await api("/terms/" + state.editingId, { method: "PUT", body: JSON.stringify(payload) });
      toast("Термин обновлён", "success");
    } else {
      await api("/terms", { method: "POST", body: JSON.stringify(payload) });
      toast("Термин добавлен", "success");
    }
    closeAll();
    await loadCategories();
    await loadTerms();
  } catch (err) { toast("Не удалось сохранить: " + err.message, "error"); }
}

async function deleteTerm(term) {
  if (!isAdmin()) return;
  if (!confirm(`Удалить термин «${term.term}»?`)) return;
  try {
    await api("/terms/" + term.id, { method: "DELETE" });
    toast("Термин удалён", "success");
    await loadCategories();
    await loadTerms();
  } catch (err) { toast("Не удалось удалить: " + err.message, "error"); }
}

async function submitLogin(e) {
  e.preventDefault();
  const f = e.target;
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: f.username.value, password: f.password.value }),
    });
    setSession(data.token, data.user);
    closeAll();
    await loadTerms();
    toast(`Добро пожаловать, ${data.user.username}!`, "success");
  } catch (err) { toast(err.message, "error"); }
}

async function submitRegister(e) {
  e.preventDefault();
  const f = e.target;
  try {
    await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username: f.username.value,
        password: f.password.value,
        email: f.email.value.trim() || null,
      }),
    });
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: f.username.value, password: f.password.value }),
    });
    setSession(data.token, data.user);
    closeAll();
    await loadTerms();
    toast(`Аккаунт создан. Привет, ${data.user.username}!`, "success");
  } catch (err) { toast(err.message, "error"); }
}

function openProfile() {
  if (!isLoggedIn()) return;
  const f = $("#profileForm");
  f.reset();
  f.username.value = state.user.username;
  f.email.value = state.user.email || "";
  openModal("#profileModal");
}

async function submitProfile(e) {
  e.preventDefault();
  const f = e.target;
  try {
    const updated = await api("/auth/profile", {
      method: "PUT",
      body: JSON.stringify({ email: f.email.value.trim() || null }),
    });
    state.user = updated;
    closeAll();
    toast("Профиль обновлён", "success");
  } catch (err) { toast(err.message, "error"); }
}

// ---------- журнал ----------
function shortUA(ua) {
  if (!ua) return "";
  const browser =
    /Edg\//.test(ua) ? "Edge" :
    /OPR\//.test(ua) ? "Opera" :
    /YaBrowser/.test(ua) ? "Yandex" :
    /Chrome\//.test(ua) ? "Chrome" :
    /Firefox\//.test(ua) ? "Firefox" :
    /Safari\//.test(ua) ? "Safari" :
    "браузер";
  const os =
    /Windows/.test(ua) ? "Windows" :
    /iPhone|iPad/.test(ua) ? "iOS" :
    /Android/.test(ua) ? "Android" :
    /Mac OS X/.test(ua) ? "macOS" :
    /Linux/.test(ua) ? "Linux" :
    "";
  return os ? `${browser} · ${os}` : browser;
}

function parseDetails(raw) {
  if (!raw) return "";
  let obj;
  try { obj = JSON.parse(raw); } catch { return escapeHtml(raw); }
  if (typeof obj !== "object" || obj === null) return escapeHtml(String(obj));

  const lines = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === "object" && "from" in v && "to" in v) {
      const from = v.from === null || v.from === undefined ? "—" : String(v.from);
      const to = v.to === null || v.to === undefined ? "—" : String(v.to);
      lines.push(`<div><b>${escapeHtml(k)}</b>: <s>${escapeHtml(from)}</s> → <b>${escapeHtml(to)}</b></div>`);
    } else if (typeof v === "object" && v !== null) {
      lines.push(`<div><b>${escapeHtml(k)}</b>: ${escapeHtml(JSON.stringify(v))}</div>`);
    } else {
      lines.push(`<div><b>${escapeHtml(k)}</b>: ${escapeHtml(String(v))}</div>`);
    }
  }
  return lines.join("");
}

async function openLogs() {
  // фильтр по пользователю — только для админа
  $("#logFilterUser").classList.toggle("hidden", !isAdmin());

  // список типов действий — загружаем один раз
  if (!logState.actionsLoaded) {
    try {
      const actions = await api("/logs/actions");
      const sel = $("#logFilterAction");
      sel.innerHTML = '<option value="">Все действия</option>' +
        actions.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join("");
      logState.actionsLoaded = true;
    } catch (e) { /* тихо */ }
  }

  logState.items = [];
  logState.offset = 0;
  $("#logsList").innerHTML = "";
  await loadLogsPage(true);
  openModal("#logsModal");
}

function buildLogParams() {
  const params = new URLSearchParams();
  const u = $("#logFilterUser").value.trim();
  const a = $("#logFilterAction").value;
  const f = $("#logFilterFrom").value;
  const t = $("#logFilterTo").value;
  if (u && isAdmin()) params.set("username", u);
  if (a) params.set("action", a);
  if (f) params.set("date_from", f);
  if (t) params.set("date_to", t);
  return params;
}

async function loadLogsPage(reset = false) {
  if (reset) {
    logState.items = [];
    logState.offset = 0;
    $("#logsList").innerHTML = "";
  }
  const params = buildLogParams();
  params.set("limit", logState.limit);
  params.set("offset", logState.offset);

  try {
    const data = await api("/logs?" + params);
    logState.total = data.total;
    logState.items = logState.items.concat(data.items);
    logState.offset += data.items.length;
    renderLogs();
    $("#logMoreBtn").classList.toggle("hidden", logState.offset >= logState.total);
    $("#logTotal").textContent =
      `Всего: ${logState.total} · показано ${logState.items.length}`;
  } catch (e) { toast(e.message, "error"); }
}

function renderLogs() {
  const box = $("#logsList");
  box.innerHTML = "";
  logState.items.forEach((r, i) => {
    const div = document.createElement("div");
    div.className = "log-row";
    div.style.setProperty("--i", Math.min(i, 30));

    const detailsHtml = parseDetails(r.details);
    const target = r.target_name ? ` · ${escapeHtml(r.target_name)}` : "";

    const metaParts = [];
    if (r.ip_address) metaParts.push(`IP: ${escapeHtml(r.ip_address)}`);
    if (r.user_agent) metaParts.push(shortUA(r.user_agent));
    if (r.session_ref) metaParts.push(`сессия #${escapeHtml(r.session_ref)}`);

    div.innerHTML = `
      <div class="log-top">
        <span><span class="log-action ${r.action}">${escapeHtml(r.action)}</span> ${escapeHtml(r.username)}${target}</span>
        <span class="log-time">${new Date(r.created_at).toLocaleString("ru")}</span>
      </div>
      ${metaParts.length ? `<div class="log-meta">${metaParts.map(m => `<span>${m}</span>`).join("")}</div>` : ""}
      ${detailsHtml ? `<div class="log-details-full">${detailsHtml}</div>` : ""}
    `;

    if (detailsHtml) {
      div.onclick = () => div.classList.toggle("expanded");
    } else {
      div.classList.add("no-details");
    }
    box.appendChild(div);
  });
}

async function exportLogsCSV() {
  const params = buildLogParams();
  try {
    const res = await fetch(API + "/logs/export?" + params, {
      headers: state.token ? { "X-Session-Token": state.token } : {},
    });
    if (!res.ok) {
      const d = await res.json().catch(() => null);
      throw new Error(d?.detail || `Ошибка ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `logs_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Файл скачан", "success");
  } catch (e) { toast("Не удалось выгрузить: " + e.message, "error"); }
}

async function openUsers() {
  try {
    const users = await api("/users");
    const box = $("#usersList");
    box.innerHTML = "";
    users.forEach((u, i) => {
      const row = document.createElement("div");
      row.className = "user-row";
      row.style.setProperty("--i", Math.min(i, 30));
      row.innerHTML = `
        <div>
          <div class="user-name">${escapeHtml(u.username)}</div>
          <div class="user-role">id ${u.id} · с ${new Date(u.created_at).toLocaleDateString("ru")}${u.email ? " · " + escapeHtml(u.email) : ""}</div>
        </div>
        <select data-uid="${u.id}">
          <option value="user" ${u.role === "user" ? "selected" : ""}>пользователь</option>
          <option value="admin" ${u.role === "admin" ? "selected" : ""}>админ</option>
        </select>
      `;
      row.querySelector("select").onchange = async (e) => {
        try {
          await api("/users/" + u.id + "/role", {
            method: "PUT",
            body: JSON.stringify({ role: e.target.value }),
          });
          toast(`Роль ${u.username} изменена`, "success");
        } catch (err) {
          toast(err.message, "error");
          e.target.value = u.role;
        }
      };
      box.appendChild(row);
    });
    openModal("#usersModal");
  } catch (e) { toast("Не удалось загрузить пользователей: " + e.message, "error"); }
}

function closeAll() {
  ["#viewModal", "#formModal", "#loginModal", "#registerModal",
   "#logsModal", "#usersModal", "#profileModal"]
    .forEach(id => $(id).classList.add("hidden"));
  state.editingId = null;
  state.viewingTerm = null;
}

// ---------- события ----------
let searchTimer;
searchInput.addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = e.target.value.trim();
    loadTerms();
  }, 250);
});

$("#addBtn").addEventListener("click", () => openForm());
$("#termForm").addEventListener("submit", submitForm);
$("#loginForm").addEventListener("submit", submitLogin);
$("#registerForm").addEventListener("submit", submitRegister);
$("#profileForm").addEventListener("submit", submitProfile);
$("#usersBtn").addEventListener("click", openUsers);
$("#logsBtn").addEventListener("click", openLogs);

$("#logApplyBtn").addEventListener("click", () => loadLogsPage(true));
$("#logResetBtn").addEventListener("click", () => {
  $("#logFilterUser").value = "";
  $("#logFilterAction").value = "";
  $("#logFilterFrom").value = "";
  $("#logFilterTo").value = "";
  loadLogsPage(true);
});
$("#logExportBtn").addEventListener("click", exportLogsCSV);
$("#logMoreBtn").addEventListener("click", () => loadLogsPage(false));

$("#profileBtn").addEventListener("click", openProfile);
$("#loginBtn").addEventListener("click", () => openModal("#loginModal"));
$("#logoutBtn").addEventListener("click", () => logout());

$("#toRegister").addEventListener("click", (e) => {
  e.preventDefault();
  closeAll();
  openModal("#registerModal");
});
$("#toLogin").addEventListener("click", (e) => {
  e.preventDefault();
  closeAll();
  openModal("#loginModal");
});

$("#randomBtn").addEventListener("click", async () => {
  try {
    const t = await api("/random");
    openView(t);
  } catch (e) { toast(e.message, "error"); }
});

document.querySelectorAll("[data-close]").forEach(el =>
  el.addEventListener("click", closeAll));
document.querySelectorAll(".modal").forEach(m =>
  m.addEventListener("click", (e) => { if (e.target === m) closeAll(); }));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

// ---------- старт ----------
(async function init() {
  attachRipple();
  await restoreSession();
  updateAuthUI();
  await loadCategories();
  await loadTerms();
})();