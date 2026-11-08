const API = "/api";
const TOKEN_KEY = "it_slang_token";

const CATEGORY_ICONS = {
  "Процесс разработки": "[ DEV ]",
  "Код и качество": "[ CODE ]",
  "Инфраструктура": "[ OPS ]",
  "Команда и роли": "[ TEAM ]",
  "Веб и API": "[ WEB ]",
  "Базы данных": "[ DB ]",
  "Безопасность": "[ SEC ]",
  "Тестирование": "[ QA ]",
  "Git": "[ GIT ]",
  "Data Science / ML": "[ AI ]",
  "Мобильная разработка": "[ MOB ]",
  "Сети": "[ NET ]",
};

const state = {
  terms: [], categories: [], activeCategory: null, search: "", view: "categories",
  editingId: null, viewingTerm: null, token: localStorage.getItem(TOKEN_KEY) || null, user: null,
};

const logState = { items: [], offset: 0, limit: 50, total: 0, actionsLoaded: false };

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");
const status = $("#status");
const searchInput = $("#search");

// --- УВЕДОМЛЕНИЯ ---
function toast(message, type = "info", timeout = 4000) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast " + type;
  let prefix = "[SYS] ";
  if (type === "error") prefix = "[ERR] ";
  if (type === "success") prefix = "[OK] ";
  if (type === "warn") prefix = "[WRN] ";
  el.textContent = prefix + message.toUpperCase();
  box.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 300);
  }, timeout);
}

// --- ТЕМА ---
const themeToggleBtn = $("#themeToggle");
if (localStorage.getItem("theme") === "light") {
    document.documentElement.setAttribute("data-theme", "light");
    themeToggleBtn.textContent = "[ ТЬМА ]";
}
themeToggleBtn.addEventListener("click", () => {
    const isLight = document.documentElement.getAttribute("data-theme") === "light";
    if (isLight) {
        document.documentElement.removeAttribute("data-theme");
        themeToggleBtn.textContent = "[ СВЕТ ]";
        localStorage.setItem("theme", "dark");
    } else {
        document.documentElement.setAttribute("data-theme", "light");
        themeToggleBtn.textContent = "[ ТЬМА ]";
        localStorage.setItem("theme", "light");
    }
});

// --- API ---
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers["X-Session-Token"] = state.token;
  const res = await fetch(API + path, { headers, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (res.status === 401 && state.token) {
    logout(true);
    throw new Error("СЕССИЯ ЗАВЕРШЕНА. ТРЕБУЕТСЯ АВТОРИЗАЦИЯ.");
  }
  if (!res.ok) {
    const msg = data?.detail || `ОШИБКА СИСТЕМЫ ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

// --- АВТОРИЗАЦИЯ ---
function isAdmin() { return state.user?.role === "admin"; }
function isLoggedIn() { return !!state.user; }

function updateAuthUI() {
  const logged = isLoggedIn(), admin = isAdmin();
  $("#addBtn").classList.toggle("hidden", !admin);
  $("#usersBtn").classList.toggle("hidden", !admin);
  $("#logsBtn").classList.toggle("hidden", !logged);
  $("#loginBtn").classList.toggle("hidden", logged);
  $("#logoutBtn").classList.toggle("hidden", !logged);
  const badge = $("#profileBtn");
  if (logged) {
    badge.textContent = `${admin ? "[ADMIN]" : "[STALKER]"} ${state.user.username.toUpperCase()}`;
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function setSession(token, user) {
  state.token = token; state.user = user;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  updateAuthUI();
}

function logout(silent = false) {
  if (state.token) fetch(API + "/auth/logout", { method: "POST", headers: { "X-Session-Token": state.token } }).catch(() => {});
  setSession(null, null);
  if (!silent) toast("ВЫХОД ИЗ СИСТЕМЫ ВЫПОЛНЕН");
  refreshView();
}

async function restoreSession() {
  if (!state.token) return;
  try {
    const me = await fetch(API + "/auth/me", { headers: { "X-Session-Token": state.token } });
    if (!me.ok) throw new Error();
    state.user = await me.json();
  } catch { setSession(null, null); }
}

// --- ЭКРАНЫ ---
function showView(view) {
  state.view = view;
  $("#categoriesView").classList.toggle("hidden", view !== "categories");
  $("#termsView").classList.toggle("hidden", view !== "terms");
}

async function refreshView() {
  if (state.search) {
    showView("terms");
    $("#backToCategoriesBtn").classList.add("hidden");
    $("#termsHeadTitle").textContent = `ПОИСК: «${state.search.toUpperCase()}»`;
    $("#termsHeadCount").textContent = "";
    await loadTerms(); return;
  }
  if (state.activeCategory) {
    showView("terms");
    $("#backToCategoriesBtn").classList.remove("hidden");
    $("#termsHeadTitle").textContent = `СЕКТОР: ${state.activeCategory.toUpperCase()}`;
    await loadTerms(); return;
  }
  showView("categories");
  await loadCategories();
  renderCategoriesView();
}

// --- ДАННЫЕ ---
async function loadCategories() {
  try {
    state.categories = await api("/categories");
    fillCategoryDatalist();
  } catch (e) {}
}

async function loadTerms() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.activeCategory && !state.search) params.set("category", state.activeCategory);
  params.set("limit", "500");
  status.textContent = "> ЗАГРУЗКА ДАННЫХ...";
  grid.innerHTML = "";
  try {
    const data = await api("/terms?" + params);
    state.terms = data.items;
    renderGrid();
    status.textContent = data.total === 0 ? "> [WRN] ЗАПИСИ НЕ НАЙДЕНЫ." : "";
    $("#termsHeadCount").textContent = data.total > 0 ? `[ НАЙДЕНО: ${data.total} ]` : "";
  } catch (e) {
    status.textContent = "> [ERR] ОШИБКА ЧТЕНИЯ БАЗЫ.";
    toast(e.message, "error");
  }
}

function renderCategoriesView() {
  const box = $("#categoriesGrid");
  box.innerHTML = "";
  state.categories.forEach((c) => {
    const card = document.createElement("div");
    card.className = "category-card";
    const icon = CATEGORY_ICONS[c.name] || "[ DATA ]";
    card.innerHTML = `<div class="cat-icon">${icon}</div><div class="cat-name">${c.name.toUpperCase()}</div><div class="cat-count">ЗАПИСЕЙ: ${c.count}</div><div class="cat-arrow">>></div>`;
    card.onclick = () => { state.activeCategory = c.name; state.search = ""; searchInput.value = ""; refreshView(); window.scrollTo({ top: 0, behavior: "smooth" }); };
    box.appendChild(card);
  });
}

function renderGrid() {
  grid.innerHTML = "";
  state.terms.forEach((t) => {
    const card = document.createElement("article");
    card.className = "card";
    card.innerHTML = `<span class="badge">[ ${t.category.toUpperCase()} ]</span><h3>${t.term}</h3><p class="short">${t.definition}</p>`;
    card.onclick = (e) => { if (!e.target.closest(".btn")) openView(t); };
    if (isAdmin()) {
      const actions = document.createElement("div");
      actions.className = "card-actions";
      actions.innerHTML = `<button class="btn ghost btn-edit">[ ИЗМЕНИТЬ ]</button><button class="btn danger btn-del">[ УДАЛИТЬ ]</button>`;
      actions.querySelector(".btn-edit").onclick = (e) => { e.stopPropagation(); openForm(t); };
      actions.querySelector(".btn-del").onclick = (e) => { e.stopPropagation(); deleteTerm(t); };
      card.appendChild(actions);
    }
    grid.appendChild(card);
  });
}

function fillCategoryDatalist() {
  const dl = $("#catList");
  dl.innerHTML = "";
  state.categories.forEach((c) => { const opt = document.createElement("option"); opt.value = c.name; dl.appendChild(opt); });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (s) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[s]);
}

// --- МОДАЛКИ ---
function openModal(id) { $(id).classList.remove("hidden"); }
function closeAll() {
  ["#viewModal", "#formModal", "#loginModal", "#registerModal", "#logsModal", "#usersModal", "#profileModal"].forEach(id => $(id).classList.add("hidden"));
  state.editingId = null; state.viewingTerm = null;
}

function openView(term) {
  state.viewingTerm = term;
  $("#viewCategory").textContent = `[ СЕКТОР: ${term.category.toUpperCase()} ]`;
  $("#viewTerm").textContent = term.term.toUpperCase();
  $("#viewDefinition").textContent = term.definition;
  const wrap = $("#viewExampleWrap");
  if (term.example && term.example.trim()) {
    $("#viewExample").textContent = `> ${term.example}`; wrap.style.display = "";
  } else { wrap.style.display = "none"; }
  $("#viewMeta").textContent = term.created_by ? `ОПЕРАТОР: ${term.created_by.toUpperCase()} // ДАТА: ${new Date(term.created_at).toLocaleString("ru")}` : "";

  let copyBtn = $("#copyTermBtn");
  if (!copyBtn) {
    copyBtn = document.createElement("button"); copyBtn.id = "copyTermBtn"; copyBtn.className = "btn ghost"; copyBtn.style.marginTop = "15px"; copyBtn.textContent = "[ СКОПИРОВАТЬ ДАННЫЕ ]";
    $("#viewModal .modal-content div[style*='padding']").appendChild(copyBtn);
  }
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(`${term.term}\n${term.definition}\n${term.example || ""}`).then(() => toast("ДАННЫЕ СКОПИРОВАНЫ", "success")).catch(() => toast("СБОЙ БУФЕРА", "error"));
  };
  openModal("#viewModal");
}

function openForm(term = null) {
  if (!isAdmin()) { toast("ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА", "warn"); return; }
  state.editingId = term ? term.id : null;
  $("#formTitle").textContent = term ? "РЕДАКТИРОВАНИЕ ЗАПИСИ" : "ВНЕСЕНИЕ НОВОЙ ЗАПИСИ";
  const form = $("#termForm"); form.reset();
  if (term) { form.term.value = term.term; form.category.value = term.category; form.definition.value = term.definition; form.example.value = term.example || ""; }
  openModal("#formModal"); form.term.focus();
}

async function submitForm(e) {
  e.preventDefault(); const form = e.target;
  const payload = { term: form.term.value.trim(), category: form.category.value.trim(), definition: form.definition.value.trim(), example: form.example.value.trim() };
  try {
    if (state.editingId) {
      await api("/terms/" + state.editingId, { method: "PUT", body: JSON.stringify(payload) }); toast("ЗАПИСЬ ОБНОВЛЕНА", "success");
    } else {
      await api("/terms", { method: "POST", body: JSON.stringify(payload) }); toast("ЗАПИСЬ ДОБАВЛЕНА", "success");
    }
    closeAll(); await afterTermChange();
  } catch (err) { toast("ОШИБКА: " + err.message, "error"); }
}

async function deleteTerm(term) {
  if (!isAdmin()) return;
  if (!confirm(`[ВНИМАНИЕ] УДАЛИТЬ «${term.term}»?`)) return;
  try { await api("/terms/" + term.id, { method: "DELETE" }); toast("ЗАПИСЬ УНИЧТОЖЕНА", "success"); await afterTermChange(); }
  catch (err) { toast("СБОЙ: " + err.message, "error"); }
}

async function afterTermChange() {
  await loadCategories();
  if (state.view === "categories") renderCategoriesView(); else await loadTerms();
}

// --- АВТОРИЗАЦИЯ ФОРМЫ ---
async function submitLogin(e) {
  e.preventDefault(); const f = e.target;
  try {
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ username: f.username.value, password: f.password.value }) });
    setSession(data.token, data.user); closeAll(); refreshView(); toast(`ДОСТУП РАЗРЕШЕН. ПРИВЕТ, ${data.user.username.toUpperCase()}`, "success");
  } catch (err) { toast(err.message, "error"); }
}

async function submitRegister(e) {
  e.preventDefault(); const f = e.target;

  if (!f.privacyConsent.checked) { toast("ТРЕБУЕТСЯ СОГЛАСИЕ (152-ФЗ)", "error"); return; }

  try {
    await api("/auth/register", { method: "POST", body: JSON.stringify({ username: f.username.value, password: f.password.value, email: f.email.value.trim() || null }) });
    const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ username: f.username.value, password: f.password.value }) });
    setSession(data.token, data.user); closeAll(); refreshView(); toast(`ПРОФИЛЬ СОЗДАН. ДОБРО ПОЖАЛОВАТЬ`, "success");
  } catch (err) { toast(err.message, "error"); }
}

function openProfile() {
  if (!isLoggedIn()) return;
  const f = $("#profileForm"); f.reset(); f.username.value = state.user.username; f.email.value = state.user.email || "";
  openModal("#profileModal");
}

async function submitProfile(e) {
  e.preventDefault(); const f = e.target;
  try {
    const updated = await api("/auth/profile", { method: "PUT", body: JSON.stringify({ email: f.email.value.trim() || null }) });
    state.user = updated; closeAll(); toast("ПРОФИЛЬ ОБНОВЛЕН", "success");
  } catch (err) { toast(err.message, "error"); }
}

// --- ЛОГИ ---
function shortUA(ua) {
  if (!ua) return "";
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /YaBrowser/.test(ua) ? "Yandex" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "браузер";
  const os = /Windows/.test(ua) ? "Windows" : /iPhone|iPad/.test(ua) ? "iOS" : /Android/.test(ua) ? "Android" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
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
      lines.push(`<div><b>${escapeHtml(k)}</b>: <s>${escapeHtml(v.from)}</s> -> <b>${escapeHtml(v.to)}</b></div>`);
    } else { lines.push(`<div><b>${escapeHtml(k)}</b>: ${escapeHtml(String(v))}</div>`); }
  }
  return lines.join("");
}

async function openLogs() {
  $("#logFilterUser").classList.toggle("hidden", !isAdmin());
  if (!logState.actionsLoaded) {
    try {
      const actions = await api("/logs/actions"); const list = Array.isArray(actions) ? actions : [];
      $("#logFilterAction").innerHTML = '<option value="">ВСЕ ДЕЙСТВИЯ</option>' + list.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a.toUpperCase())}</option>`).join("");
      logState.actionsLoaded = true;
    } catch (e) {}
  }
  logState.items = []; logState.offset = 0; $("#logsList").innerHTML = "";
  await loadLogsPage(true); openModal("#logsModal");
}

function buildLogParams() {
  const params = new URLSearchParams(); const u = $("#logFilterUser").value.trim(); const a = $("#logFilterAction").value; const f = $("#logFilterFrom").value; const t = $("#logFilterTo").value;
  if (u && isAdmin()) params.set("username", u); if (a) params.set("action", a); if (f) params.set("date_from", f); if (t) params.set("date_to", t);
  return params;
}

async function loadLogsPage(reset = false) {
  if (reset) { logState.items = []; logState.offset = 0; $("#logsList").innerHTML = ""; }
  const params = buildLogParams(); params.set("limit", logState.limit); params.set("offset", logState.offset);
  try {
    const data = await api("/logs?" + params);
    const items = Array.isArray(data) ? data : (data?.items || []); const total = Array.isArray(data) ? data.length : (data?.total || 0);
    logState.total = total; logState.items = logState.items.concat(items); logState.offset += items.length;
    renderLogs(); $("#logMoreBtn").classList.toggle("hidden", logState.offset >= logState.total);
    $("#logTotal").textContent = `ВСЕГО: ${logState.total} // ОТОБРАЖЕНО: ${logState.items.length}`;
  } catch (e) { toast(e.message, "error"); }
}

function renderLogs() {
  const box = $("#logsList"); box.innerHTML = "";
  logState.items.forEach((r) => {
    const div = document.createElement("div"); div.className = "log-row";
    const detailsHtml = parseDetails(r.details); const target = r.target_name ? ` // ${escapeHtml(r.target_name).toUpperCase()}` : "";
    const meta = [];
    if (r.ip_address) meta.push(`IP: ${r.ip_address}`); if (r.user_agent) meta.push(shortUA(r.user_agent)); if (r.session_ref) meta.push(`СЕССИЯ: #${r.session_ref}`);
    div.innerHTML = `
      <div class="log-top"><span><span class="log-action ${r.action}">[${r.action.toUpperCase()}]</span> ${escapeHtml(r.username).toUpperCase()}${target}</span><span class="log-time">${new Date(r.created_at).toLocaleString("ru")}</span></div>
      ${meta.length ? `<div class="log-meta">${meta.map(m => `<span>[ ${m} ]</span>`).join("")}</div>` : ""}
      ${detailsHtml ? `<div class="log-details-full">${detailsHtml}</div>` : ""}`;
    if (detailsHtml) div.onclick = () => div.classList.toggle("expanded"); else div.classList.add("no-details");
    box.appendChild(div);
  });
}

async function exportLogsCSV() {
  const params = buildLogParams();
  try {
    const res = await fetch(API + "/logs/export?" + params, { headers: state.token ? { "X-Session-Token": state.token } : {} });
    if (!res.ok) throw new Error("ОШИБКА " + res.status);
    const blob = await res.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a");
    a.href = url; a.download = `logs_${new Date().toISOString().slice(0, 10)}.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    toast("ЭКСПОРТ ЗАВЕРШЕН", "success");
  } catch (e) { toast("СБОЙ ЭКСПОРТА", "error"); }
}

async function openUsers() {
  try {
    const users = await api("/users"); const box = $("#usersList"); box.innerHTML = "";
    users.forEach((u) => {
      const row = document.createElement("div"); row.className = "user-row";
      row.innerHTML = `<div><div class="user-name">${escapeHtml(u.username).toUpperCase()}</div><div class="user-role">ID: ${u.id} // С: ${new Date(u.created_at).toLocaleDateString("ru")}${u.email ? " // " + escapeHtml(u.email) : ""}</div></div>
        <select data-uid="${u.id}"><option value="user" ${u.role === "user" ? "selected" : ""}>ОПЕРАТОР</option><option value="admin" ${u.role === "admin" ? "selected" : ""}>АДМИНИСТРАТОР</option></select>`;
      row.querySelector("select").onchange = async (e) => {
        try { await api("/users/" + u.id + "/role", { method: "PUT", body: JSON.stringify({ role: e.target.value }) }); toast(`ПРАВА ИЗМЕНЕНЫ`, "success"); }
        catch (err) { toast(err.message, "error"); e.target.value = u.role; }
      };
      box.appendChild(row);
    });
    openModal("#usersModal");
  } catch (e) { toast("СБОЙ ЗАГРУЗКИ", "error"); }
}

// --- СОБЫТИЯ ---
let searchTimer;
searchInput.addEventListener("input", (e) => {
  // ==========================================
  // ПАСХАЛКА "КТО ТЫ СТАЛКЕР" (Викторович)
  // ==========================================
  if (e.target.value.trim().toLowerCase() === "викторович") {
    e.target.value = "";
    triggerStalkerEgg();
    return;
  }

  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = e.target.value.trim();
    if (state.search) state.activeCategory = null;
    refreshView();
  }, 250);
});

$("#backToCategoriesBtn").addEventListener("click", () => { state.activeCategory = null; state.search = ""; searchInput.value = ""; refreshView(); window.scrollTo({ top: 0, behavior: "smooth" }); });
$("#addBtn").addEventListener("click", () => openForm());
$("#termForm").addEventListener("submit", submitForm);
$("#loginForm").addEventListener("submit", submitLogin);
$("#registerForm").addEventListener("submit", submitRegister);
$("#profileForm").addEventListener("submit", submitProfile);
$("#usersBtn").addEventListener("click", openUsers);
$("#logsBtn").addEventListener("click", openLogs);
$("#logApplyBtn").addEventListener("click", () => loadLogsPage(true));
$("#logResetBtn").addEventListener("click", () => { $("#logFilterUser").value = ""; $("#logFilterAction").value = ""; $("#logFilterFrom").value = ""; $("#logFilterTo").value = ""; loadLogsPage(true); });
$("#logExportBtn").addEventListener("click", exportLogsCSV);
$("#logMoreBtn").addEventListener("click", () => loadLogsPage(false));
$("#profileBtn").addEventListener("click", openProfile);
$("#loginBtn").addEventListener("click", () => openModal("#loginModal"));
$("#logoutBtn").addEventListener("click", () => logout());
$("#toRegister").addEventListener("click", (e) => { e.preventDefault(); closeAll(); openModal("#registerModal"); });
$("#toLogin").addEventListener("click", (e) => { e.preventDefault(); closeAll(); openModal("#loginModal"); });
$("#randomBtn").addEventListener("click", async () => { try { openView(await api("/random")); } catch (e) { toast(e.message, "error"); } });

document.querySelectorAll("[data-close]").forEach(el => el.addEventListener("click", closeAll));
document.querySelectorAll(".modal").forEach(m => m.addEventListener("click", (e) => { if (e.target === m) closeAll(); }));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

// ==========================================
// ПАСХАЛКА 1: "ФОНАРИК" (Клик по зеленой точке)
// ==========================================
let dotClicks = 0;
let dotTimer;
const statusDot = document.getElementById("statusDot");

if (statusDot) {
    statusDot.style.cursor = "pointer";
    statusDot.addEventListener("click", () => {
        dotClicks++;
        clearTimeout(dotTimer);
        dotTimer = setTimeout(() => { dotClicks = 0; }, 1500);

        if (dotClicks === 5) {
            dotClicks = 0;
            statusDot.style.background = "#a83232";
            statusDot.style.boxShadow = "0 0 20px #a83232";
            toast("ВНИМАНИЕ: ОБНАРУЖЕНА АНОМАЛИЯ. НАДЕНЬТЕ ПРОТИВОГАЗ.", "error", 4000);
            document.documentElement.setAttribute("data-theme", "light");

            setTimeout(() => {
                document.documentElement.removeAttribute("data-theme");
                statusDot.style.background = "#4af626";
                statusDot.style.boxShadow = "0 0 8px #4af626";
                toast("ФОНАРИК СЕЛ. ПЕРЕХОД НА РЕЗЕРВНОЕ ПИТАНИЕ.", "info", 4000);
            }, 3000);
        }
    });
}

// ==========================================
// ПАСХАЛКА 2: "КТО ТЫ СТАЛКЕР" (Ввод в поиск)
// ==========================================
function triggerStalkerEgg() {
    const overlay = document.getElementById("stalkerOverlay");
    const textEl = document.getElementById("stalkerText");
    const phrase = "КТО ТЫ СТАЛКЕР?";

    overlay.classList.remove("hidden");
    textEl.textContent = "";

    let i = 0;
    const typeInterval = setInterval(() => {
        textEl.textContent += phrase[i];
        i++;
        if (i >= phrase.length) {
            clearInterval(typeInterval);
        }
    }, 120);

    setTimeout(() => {
        overlay.style.transition = "opacity 1s";
        overlay.style.opacity = "0";
        setTimeout(() => {
            overlay.classList.add("hidden");
            overlay.style.opacity = "1";
            overlay.style.transition = "";
            textEl.textContent = "";
        }, 1000);
    }, 4000);
}

// Секретное сообщение в консоль
console.log("%c[METRO_DICT_SYS v2.0 // SECURE TERMINAL]", "color: #d17a22; font-size: 20px; font-weight: bold; background: #000; padding: 10px; border: 2px solid #d17a22;");
console.log("%cЕсли ты открыл консоль, значит, ты знаешь, что делаешь. Добро пожаловать в Спарту, сталкер. Жди сигнала. 2033 год.", "color: #4af626; font-size: 14px; font-family: monospace;");

// --- СТАРТ ---
(async function init() {
  await restoreSession();
  updateAuthUI();
  await refreshView();
})();