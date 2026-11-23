const app = document.querySelector("#app");
const notice = document.querySelector("#notice");
let model = null;
let tab = "";
let noticeTimer;
let busy = false;

const pages = {
  coordinator: [["overview", "Распределение", "grid"], ["students", "Студенты", "people"],
    ["places", "Базы практики", "box"], ["audit", "Журнал действий", "list"]],
  student: [["student", "Моя практика", "grid"]],
  partner: [["partner", "Отклики и места", "box"]],
};
const roles = {coordinator: "Координатор", student: "Студент", partner: "Организация"};
const symbols = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3 19v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2m2-14a3 3 0 0 1 0 6m4 8v-2a4 4 0 0 0-3-4"/>',
  box: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V4h8v3M3 12h18m-11 0v3h4v-3"/>',
  list: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',
};
const esc = value => String(value ?? "").replace(/[&<>"']/g, char =>
  ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
const icon = key => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${symbols[key]}</svg>`;
const brand = () => '<div class="brand"><img src="/mark.svg" alt="">Практика МПТ</div>';
const heading = (title, caption) => `<div class="page-head"><h1>${title}</h1><p class="muted">${caption}</p></div>`;
const pill = (text, color = "") => `<span class="pill ${color}">${text}</span>`;
const empty = text => `<p class="empty">${text}</p>`;
const option = (value, label, selected = false) =>
  `<option value="${esc(value)}" ${selected ? "selected" : ""}>${esc(label)}</option>`;
const profileOptions = () => model.profiles.map(profile => option(profile, profile)).join("");

async function api(path, body) {
  const init = body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  };
  const response = await fetch("/api/" + path, init);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "Запрос не выполнен.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function message(text, error = false) {
  clearTimeout(noticeTimer);
  notice.textContent = text;
  notice.className = error ? "error" : "";
  noticeTimer = setTimeout(() => { notice.textContent = ""; }, 4500);
}

function login() {
  return `<div class="login-shell">
    <section class="login-intro">${brand()}<h1>Производственная практика</h1>
    <p>Места практики, отклики организаций и распределение студентов в одном кабинете.</p></section>
    <main class="login-main"><h2>Вход в систему</h2>
    <form data-form="login">
      <label>Логин<input name="login" maxlength="40" autocomplete="username" required></label>
      <label>Пароль<input name="password" type="password" maxlength="96" autocomplete="current-password" required></label>
      <button>Войти</button>
    </form>
    <section class="demo"><p class="muted small-text">Заполнить форму демонстрационными данными</p>
    <div class="actions">${Object.entries(roles).map(([key, label]) =>
      `<button class="secondary small" data-demo="${key}">${label}</button>`).join("")}</div></section></main>
  </div>`;
}

function table(headers, body) {
  return `<div class="table-scroll"><table><thead><tr>${headers.map(header =>
    `<th scope="col">${header}</th>`).join("")}</tr></thead><tbody>${body.join("")}</tbody></table></div>`;
}
function panel(title, body, controls = "") {
  return `<section class="panel"><header class="panel-head"><h2>${title}</h2>${controls}</header>${body}</section>`;
}
function assignments(items, fallback) {
  if (!items.length) return empty(fallback);
  return table(["Студент", "Организация и место", "Приоритет"], items.map(item => `<tr>
    <td><strong>${esc(item.student)}</strong><span class="muted">${esc(item.cohort)}</span></td>
    <td><strong>${esc(item.organization)}</strong><span class="muted">${esc(item.title)}</span></td>
    <td>${pill("№ " + item.rank)}</td></tr>`));
}

function overview() {
  const assigned = new Set(model.assignments.map(item => item.student_id));
  const total = model.places.reduce((count, item) => count + item.capacity, 0);
  const waiting = model.students.filter(item => !assigned.has(item.id));
  const metrics = [[model.students.length, "Студентов в списке"], [total, "Мест по квоте"],
    [assigned.size, "Назначено"], [waiting.length, "Без назначения"]];
  const progress = model.published ? "Распределение опубликовано" :
    model.assignments.length ? "Черновик распределения" : "Назначений пока нет";
  return heading("Распределение", "Производственная практика · кабинет координатора") +
    `<section class="hero"><div><h2>${progress}</h2><p class="muted">${model.published ?
      "Студенты и организации видят свои назначения." :
      "Расчёт учитывает направление, квоты, приоритеты студентов и отклики организаций."}</p></div>
    <div class="actions">${model.published ?
      '<button class="secondary" data-action="withdraw">Отозвать публикацию</button>' :
      `<button data-action="calculate">Рассчитать</button><button class="secondary" data-action="publish"
        ${assigned.size ? "" : "disabled"}>Опубликовать</button>`}</div></section>
    <section class="summary" aria-label="Сводка распределения">${metrics.map(([count, label]) =>
      `<div class="metric"><strong>${count}</strong><span class="muted small-text">${label}</span></div>`).join("")}</section>` +
    panel("Назначения", assignments(model.assignments, "Рассчитайте распределение, чтобы увидеть назначения."),
      assigned.size ? '<a class="button secondary small" href="/api/export">Скачать CSV</a>' : "") +
    panel("Без назначения", waiting.length ? table(["Студент", "Группа", "Причина"], waiting.map(item =>
      `<tr><td>${esc(item.name)}</td><td>${esc(item.cohort)}</td><td>${item.preferences ?
        (assigned.size ? "Нет назначения по выбранным местам" : "Поданы приоритеты") :
        "Приоритеты не поданы"}</td></tr>`)) : empty("Все студенты получили назначение."));
}

function students() {
  const form = model.published ? "" : `<details><summary>Добавить студента</summary>
    <form data-form="students" class="form-grid">
      <label>ФИО<input name="name" maxlength="100" required></label>
      <label>Группа<input name="cohort" maxlength="32" required></label>
      <label>Направление<select name="profile">${profileOptions()}</select></label>
      <label>Логин<input name="login" maxlength="40" pattern="[a-zA-Z0-9_\\-]+" required></label>
      <label>Пароль<input name="password" type="password" minlength="10" maxlength="96" autocomplete="new-password" required></label>
      <div class="actions"><button>Добавить</button></div>
    </form></details>`;
  const filter = '<input class="find" id="find-student" type="search" placeholder="Найти студента" aria-label="Найти студента">';
  return heading("Студенты", "Участники распределения и поданные приоритеты.") +
    panel("Список студентов", form + table(["Студент", "Группа и направление", "Приоритеты", "Логин"],
      model.students.map(item => `<tr data-student-row>
        <td><strong>${esc(item.name)}</strong></td><td>${esc(item.cohort)}<span class="muted">${esc(item.profile)}</span></td>
        <td>${item.preferences ? pill(item.preferences + " из 3") : pill("Не поданы", "wait")}</td>
        <td>${esc(item.login)}</td></tr>`)), filter);
}

function places() {
  const add = model.published ? "" : `<details><summary>Добавить организацию</summary>
    <form class="form-grid" data-form="organizations"><label>Название<input name="name" maxlength="100" required></label>
    <div class="actions"><button>Добавить</button></div></form></details>
    <details><summary>Добавить место</summary>
    <form class="form-grid" data-form="places">
      <label>Организация<select name="organization_id">${model.organizations.map(item => option(item.id, item.name)).join("")}</select></label>
      <label>Наименование места<input name="title" maxlength="100" required></label>
      <label>Направление<select name="profile">${profileOptions()}</select></label>
      <label>Квота<input type="number" name="capacity" min="1" max="100" required></label>
      <div class="actions"><button>Добавить</button></div>
    </form></details>
    <details><summary>Изменить квоту</summary>
    <form class="form-grid" data-form="capacity">
      <label>Место<select name="place_id">${model.places.map(item => option(item.id, item.title)).join("")}</select></label>
      <label>Новая квота<input type="number" name="capacity" min="1" max="100" required></label>
      <div class="actions"><button>Сохранить</button></div>
    </form></details>`;
  return heading("Базы практики", "Организации, направления подготовки и доступные квоты.") +
    panel("Предложения организаций", add + table(["Организация и место", "Направление", "Квота", "Назначено"],
      model.places.map(item => `<tr><td><strong>${esc(item.organization)}</strong>
        <span class="muted">${esc(item.title)}</span></td><td>${esc(item.profile)}</td>
        <td>${item.capacity}</td><td>${pill(item.occupied + " из " + item.capacity, item.occupied ? "yes" : "")}</td></tr>`)));
}

function audit() {
  return heading("Журнал действий", "Последние 30 изменений, сохранённых в системе.") +
    panel("История изменений", table(["Дата и время", "Логин", "Действие"], model.audit.map(item =>
      `<tr><td>${esc(new Date(item.recorded).toLocaleString("ru-RU"))}</td><td>${esc(item.login)}</td>
      <td>${esc(item.event)}</td></tr>`)));
}

function student() {
  const selected = new Map(model.preferences.map(item => [item.rank, item.place_id]));
  const preferences = [1, 2, 3].map(rank => {
    const place = model.places.find(item => item.id === selected.get(rank));
    if (model.published) {
      return `<div class="rank-view"><strong>Приоритет ${rank}</strong>
        <span>${place ? esc(place.organization + " · " + place.title) : "Не выбран"}</span></div>`;
    }
    return `<label>Приоритет ${rank}<select name="rank${rank}">${option("", "Не выбран")}
      ${model.places.map(item => option(item.id, item.organization + " · " + item.title, selected.get(rank) === item.id)).join("")}
    </select></label>`;
  }).join("");
  const result = model.assignments[0];
  const outcome = result ? "Назначение опубликовано" : model.published ? "Назначение отсутствует" : "Результат ожидает публикации";
  return heading("Моя практика", `${esc(model.student.name)} · ${esc(model.student.cohort)} · ${esc(model.student.profile)}`) +
    `<section class="hero"><div><h2>${outcome}</h2><p class="muted">${result ?
      `${esc(result.organization)} · ${esc(result.title)} · приоритет № ${result.rank}` :
      model.published ? "Уточните дальнейшие действия у координатора." : "После публикации здесь появится ваше назначение."}</p></div></section>` +
    `<div class="two">${panel("Приоритеты", `<div class="panel-body"><p class="muted small-text">${model.published ? "Приоритеты зафиксированы на момент публикации." : "Выберите до трёх мест в порядке предпочтения."}</p>
        <form data-form="preferences" class="stack">${preferences}${model.published ? "" : '<div><button>Сохранить приоритеты</button></div>'}</form></div>`)}
      ${panel("Резюме", `<div class="panel-body"><p class="muted small-text">Резюме видно организациям, места которых вы выбрали.</p>
        <form data-form="resume" class="stack"><label>Навыки и опыт<textarea name="resume" maxlength="1200">${esc(model.student.resume)}</textarea></label>
        <div><button>Сохранить резюме</button></div></form></div>`)}</div>` +
    panel("Отклики организаций", model.feedback.length ? table(["Организация", "Место", "Комментарий"],
      model.feedback.map(item => `<tr><td>${esc(item.organization)}</td><td>${esc(item.title)}</td>
        <td>${esc(item.comment || "Заинтересованы")}</td></tr>`)) : empty("Откликов пока нет."));
}

function partner() {
  const applicants = model.applicants.map(item => `<details class="applicant"><summary>
    ${esc(item.name)} · ${esc(item.title)} ${item.interested ? pill("Есть отклик", "yes") : ""}</summary>
    <p class="muted">${esc(item.cohort)} · ${esc(item.resume || "Резюме пока не заполнено.")}</p>
    ${model.published ? `<p>${esc(item.comment || "")}</p>` : `<form data-form="feedback" class="stack">
      <input type="hidden" name="student_id" value="${item.student_id}"><input type="hidden" name="place_id" value="${item.place_id}">
      <label>Комментарий<textarea name="comment" maxlength="500">${esc(item.comment)}</textarea></label>
      <div class="actions"><button name="interest" value="yes">Заинтересованы</button>
      ${item.interested ? '<button class="secondary" name="interest" value="no">Снять отклик</button>' : ""}</div>
    </form>`}</details>`).join("");
  return heading("Отклики и места", esc(model.organization)) +
    panel("Места вашей организации", table(["Место", "Направление", "Квота"], model.places.map(item =>
      `<tr><td>${esc(item.title)}</td><td>${esc(item.profile)}</td><td>${item.capacity}</td></tr>`))) +
    panel("Заявки студентов", applicants || empty("Студенты пока не выбрали ваши места.")) +
    panel("Опубликованные назначения", assignments(model.assignments, "Опубликованных назначений пока нет."));
}

const renderPage = {overview, students, places, audit, student, partner};

function render() {
  if (!model) {
    app.innerHTML = login();
    return;
  }
  const nav = pages[model.role];
  if (!nav.some(([id]) => id === tab)) tab = nav[0][0];
  app.innerHTML = `<div class="shell"><aside class="sidebar">${brand()}
    <nav aria-label="Разделы кабинета">${nav.map(([id, name, symbol]) =>
      `<button data-tab="${id}" ${tab === id ? 'aria-current="page"' : ""}>${icon(symbol)}${name}</button>`).join("")}</nav>
    <div class="sidebar-footer"><div><strong>${roles[model.role]}</strong><small>${esc(model.login)}</small></div>
      <button class="small" data-action="logout">Выйти</button></div></aside>
    <main><header class="top"><div class="top-inner"><strong>Кабинет практики</strong>
      ${pill(model.published ? "Результаты опубликованы" : "Демонстрационный набор", model.published ? "yes" : "")}
    </div></header><div class="wrap">${renderPage[tab]()}</div></main></div>`;
}

async function refresh() {
  try {
    model = await api("state");
  } catch (error) {
    if (error.status !== 401) throw error;
    model = null;
  }
  render();
}

async function submit(path, data, target) {
  if (busy) return;
  busy = true;
  if (target) target.disabled = true;
  try {
    const response = await api(path, data);
    await refresh();
    if (response.message) message(response.message);
  } catch (error) {
    if (error.status === 401 && path !== "login") await refresh();
    message(error.message, true);
  } finally {
    busy = false;
    if (target) target.disabled = false;
  }
}

app.addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const {demo, tab: nextTab, action} = button.dataset;
  if (demo) {
    const form = app.querySelector("form");
    form.elements.login.value = demo;
    form.elements.password.value = "Practice2026!";
    form.querySelector('button[type="submit"], button:not([type])').focus();
  }
  if (nextTab) {
    tab = nextTab;
    render();
    app.querySelector('[aria-current="page"]').focus();
    window.scrollTo(0, 0);
  }
  if (action) void submit(action, {}, button);
});

app.addEventListener("submit", event => {
  event.preventDefault();
  const form = event.target;
  const path = form.dataset.form;
  const values = Object.fromEntries(new FormData(form));
  if (path === "preferences") {
    const selected = [values.rank1, values.rank2, values.rank3];
    if (selected.some((value, index) => value && selected.slice(0, index).includes(""))) {
      message("Заполните приоритеты последовательно, начиная с первого.", true);
      return;
    }
    void submit(path, {places: selected.filter(Boolean).map(Number)}, event.submitter);
    return;
  }
  for (const key of ["capacity", "organization_id", "student_id", "place_id"]) {
    if (key in values) values[key] = Number(values[key]);
  }
  if (path === "feedback") values.interested = event.submitter?.value !== "no";
  void submit(path, values, event.submitter);
});

app.addEventListener("input", event => {
  if (event.target.id !== "find-student") return;
  const query = event.target.value.trim().toLocaleLowerCase("ru");
  app.querySelectorAll("[data-student-row]").forEach(row => {
    row.hidden = !row.textContent.toLocaleLowerCase("ru").includes(query);
  });
});

refresh().catch(error => { render(); message(error.message, true); });


