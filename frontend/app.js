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

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");
const status = $("#status");
const searchInput = $("#search");
const categoriesNav = $("#categories");

// ---------- тосты ----------
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

// ---------- ripple ----------
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

// ---------- сеть ----------
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

// ---------- auth ----------
function isAdmin() { return state.user?.role === "admin"; }
function isLoggedIn() { return !!state.user; }

function updateAuthUI() {
  const logged = isLoggedIn();
  const admin = isAdmin();
  $("#addBtn").classList.toggle("hidden", !logged);
  $("#loginBtn").classList.toggle("hidden", logged);
  $("#logoutBtn").classList.toggle("hidden", !logged);
  $("#logsBtn").classList.toggle("hidden", !admin);
  $("#usersBtn").classList.toggle("hidden", !admin);
  const badge = $("#userBadge");
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

// ---------- загрузка ----------
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

// ---------- отрисовка ----------
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

    const canEdit = isAdmin() || (state.user && t.created_by === state.user.username);
    if (canEdit) {
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

// ---------- модалки ----------
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
  if (!isLoggedIn()) { toast("Войдите, чтобы добавлять термины.", "warn"); return; }
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
      body: JSON.stringify({ username: f.username.value, password: f.password.value }),
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

async function openLogs() {
  try {
    const rows = await api("/logs?limit=300");
    const box = $("#logsList");
    box.innerHTML = "";
    rows.forEach((r, i) => {
      const div = document.createElement("div");
      div.className = "log-row";
      div.style.setProperty("--i", Math.min(i, 30));
      const details = r.details ? `<div class="log-details">${escapeHtml(r.details)}</div>` : "";
      const target = r.target_name ? ` · ${escapeHtml(r.target_name)}` : "";
      div.innerHTML = `
        <div class="log-top">
          <span><span class="log-action ${r.action}">${r.action}</span> ${escapeHtml(r.username)}${target}</span>
          <span class="log-time">${new Date(r.created_at).toLocaleString("ru")}</span>
        </div>
        ${details}
      `;
      box.appendChild(div);
    });
    openModal("#logsModal");
  } catch (e) { toast("Не удалось загрузить журнал: " + e.message, "error"); }
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
          <div class="user-role">id ${u.id} · с ${new Date(u.created_at).toLocaleDateString("ru")}</div>
        </div>
        <select data-uid="${u.id}">
          <option value="user" ${u.role==="user"?"selected":""}>пользователь</option>
          <option value="admin" ${u.role==="admin"?"selected":""}>админ</option>
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
  ["#viewModal", "#formModal", "#loginModal", "#registerModal", "#logsModal", "#usersModal"]
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
$("#logsBtn").addEventListener("click", openLogs);
$("#usersBtn").addEventListener("click", openUsers);

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