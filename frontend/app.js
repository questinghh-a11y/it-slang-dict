const API = "/api";

const state = {
  terms: [],
  categories: [],
  activeCategory: null,
  search: "",
  editingId: null,
  viewingTerm: null,
};

const $ = (sel) => document.querySelector(sel);
const grid = $("#grid");
const status = $("#status");
const searchInput = $("#search");
const categoriesNav = $("#categories");

// ---------- сетевые вызовы ----------
async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = data?.detail || `Ошибка ${res.status}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

// ---------- загрузка данных ----------
async function loadTerms() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.activeCategory) params.set("category", state.activeCategory);

  status.textContent = "Загружаю…";
  grid.innerHTML = "";

  try {
    const data = await api("/terms?" + params.toString());
    state.terms = data.items;
    renderGrid();
    status.textContent = data.total === 0
      ? "Ничего не найдено."
      : `Найдено: ${data.total}`;
  } catch (e) {
    status.textContent = "Ошибка: " + e.message;
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
  for (const t of state.terms) {
    const card = document.createElement("article");
    card.className = "card";
    card.onclick = () => openView(t);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = t.category;

    const h3 = document.createElement("h3");
    h3.textContent = t.term;

    const p = document.createElement("p");
    p.className = "short";
    p.textContent = t.definition;

    card.append(badge, h3, p);
    grid.appendChild(card);
  }
}

function renderCategories() {
  categoriesNav.innerHTML = "";

  const all = document.createElement("button");
  all.className = "cat-chip" + (state.activeCategory === null ? " active" : "");
  all.textContent = "Все";
  all.onclick = () => { state.activeCategory = null; loadTerms(); renderCategories(); };
  categoriesNav.appendChild(all);

  for (const c of state.categories) {
    const chip = document.createElement("button");
    chip.className = "cat-chip" + (state.activeCategory === c.name ? " active" : "");
    chip.innerHTML = `${escapeHtml(c.name)}<span class="count">${c.count}</span>`;
    chip.onclick = () => {
      state.activeCategory = c.name;
      loadTerms();
      renderCategories();
    };
    categoriesNav.appendChild(chip);
  }
}

function fillCategoryDatalist() {
  const dl = $("#catList");
  dl.innerHTML = "";
  for (const c of state.categories) {
    const opt = document.createElement("option");
    opt.value = c.name;
    dl.appendChild(opt);
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (s) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[s]);
}

// ---------- модалка просмотра ----------
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
  $("#viewModal").classList.remove("hidden");
}

// ---------- модалка формы ----------
function openForm(term = null) {
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
  $("#formModal").classList.remove("hidden");
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
      await api("/terms/" + state.editingId, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/terms", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    closeAll();
    await loadCategories();
    await loadTerms();
  } catch (err) {
    alert("Не получилось сохранить: " + err.message);
  }
}

async function deleteCurrent() {
  if (!state.viewingTerm) return;
  if (!confirm(`Удалить термин «${state.viewingTerm.term}»?`)) return;
  try {
    await api("/terms/" + state.viewingTerm.id, { method: "DELETE" });
    closeAll();
    await loadCategories();
    await loadTerms();
  } catch (err) {
    alert("Не получилось удалить: " + err.message);
  }
}

function closeAll() {
  $("#viewModal").classList.add("hidden");
  $("#formModal").classList.add("hidden");
  state.editingId = null;
  state.viewingTerm = null;
}

// ---------- обработчики ----------
let searchTimer;
searchInput.addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.search = e.target.value.trim();
    loadTerms();
  }, 250);
});

$("#addBtn").addEventListener("click", () => openForm());
$("#editBtn").addEventListener("click", () => {
  const t = state.viewingTerm;
  closeAll();
  openForm(t);
});
$("#deleteBtn").addEventListener("click", deleteCurrent);
$("#termForm").addEventListener("submit", submitForm);

$("#randomBtn").addEventListener("click", async () => {
  try {
    const t = await api("/random");
    openView(t);
  } catch (e) { alert(e.message); }
});

document.querySelectorAll("[data-close]").forEach((el) => {
  el.addEventListener("click", closeAll);
});
document.querySelectorAll(".modal").forEach((m) => {
  m.addEventListener("click", (e) => {
    if (e.target === m) closeAll();
  });
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAll();
});

// ---------- старт ----------
(async function init() {
  await loadCategories();
  await loadTerms();
})();