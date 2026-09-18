"use strict";

const DAYS = ["пн", "вт", "ср", "чт", "пт", "сб"];
const DAY_FULL = { "пн": "понедельник", "вт": "вторник", "ср": "среда",
                   "чт": "четверг", "пт": "пятница", "сб": "суббота" };

let S = null;              // состояние с сервера
let curClass = null;
let curTeacher = null;
let curLesson = null;

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2600);
}

async function api(path, body) {
  const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { toast(data.error || "ошибка запроса"); throw new Error(data.error || r.status); }
  return data;
}

// ---------- данные ----------
const classById = id => S.model.classes.find(c => c.id === id);
const teacherById = id => S.model.teachers.find(t => t.id === id);
const lessonsOf = cls => S.model.lessons.filter(l => l.cls === cls);
const gradeOf = cls => parseInt(cls, 10) || 0;

function maxLesson(list) {
  return list.reduce((m, l) => Math.max(m, l.n), 0);
}

function issuesFor(cls) {
  return S.analysis.issues.filter(i => i.cls === cls);
}

// ---------- расписание класса ----------
function renderClassList() {
  const box = $("#class-list");
  box.innerHTML = "";
  S.model.classes.forEach(c => {
    const b = el("button", c.id === curClass ? "on" : "", c.id);
    const bad = issuesFor(c.id).some(i => i.level === "error");
    if (bad) b.style.borderColor = "var(--red)";
    b.onclick = () => { curClass = c.id; renderClassList(); renderGrid(); };
    box.appendChild(b);
  });
}

function renderDaybars() {
  const box = $("#daybars");
  box.innerHTML = "";
  const st = S.analysis.stats[curClass];
  if (!st) return;
  const days = classById(curClass).days === 5 ? DAYS.slice(0, 5) : DAYS;
  days.forEach(d => {
    const v = st.days[d] || { count: 0, score: 0, share: 0, fits: [] };
    const bar = el("div", "daybar " + (v.fits.length ? "ok" : "off"));
    bar.appendChild(el("b", null, DAY_FULL[d]));
    const line = el("div", "v", `${v.score} б.`);
    line.appendChild(el("span", "muted", `  ${v.count} ур.`));
    bar.appendChild(line);
    bar.appendChild(el("div", "s", v.fits.length
      ? `${v.share}% · вариант ${v.fits.join(", ")}`
      : `${v.share}% · вне нормы`));
    box.appendChild(bar);
  });
  const total = el("div", "daybar");
  total.appendChild(el("b", null, "за неделю"));
  total.appendChild(el("div", "v", `${st.total} б.`));
  total.appendChild(el("div", "s", `${st.week} уроков${st.extra ? ` + ${st.extra} внеур.` : ""}`));
  box.appendChild(total);
}

function renderGrid() {
  if (!curClass) return;
  const cls = classById(curClass);
  const list = lessonsOf(curClass);
  $("#grid-title").textContent = `${curClass} класс`;
  const errs = issuesFor(curClass);
  const st0 = S.analysis.stats[curClass] || { week: list.length, extra: 0 };
  $("#grid-meta").textContent =
    `${cls.shift} смена${cls.room ? " · кабинет " + cls.room : ""} · ${st0.week} уроков` +
    (st0.extra ? ` + ${st0.extra} внеурочных` : "") +
    (errs.length ? ` · ${errs.length} замечаний` : "");
  renderDaybars();

  const days = cls.days === 5 ? DAYS.slice(0, 5) : DAYS;
  const rows = Math.max(maxLesson(list), 6);
  const bells = S.model.bells[String(cls.shift)] || {};
  const g = $("#grid");
  g.innerHTML = "";
  g.style.gridTemplateColumns = `54px repeat(${days.length}, minmax(0, 1fr))`;
  g.appendChild(el("div", "cell head", ""));
  days.forEach(d => g.appendChild(el("div", "cell head", DAY_FULL[d])));

  for (let n = 1; n <= rows; n++) {
    const num = el("div", "cell num", String(n));
    if (bells[n]) num.appendChild(el("small", null, bells[n].split("—")[0]));
    g.appendChild(num);
    days.forEach(d => {
      const here = list.filter(l => l.day === d && l.n === n);
      const cell = el("div", "cell slot");
      cell.dataset.day = d; cell.dataset.n = n;
      if (here.length) {
        const l = here[0];
        cell.draggable = true;
        cell.dataset.id = l.id;
        const sc = scoreOf(l);
        here.forEach((x, i) => {
          const s = el("div", "subj", x.subject);
          if (i === 0 && sc != null) {
            const b = el("span", "sc", sc);
            s.prepend(b);
          }
          cell.appendChild(s);
          const t = x.teacher ? teacherById(x.teacher) : null;
          cell.appendChild(el("div", "who" + (t ? "" : " none"),
            t ? shortName(t.name) : "учитель не назначен"));
        });
        if (curLesson && curLesson.id === l.id) cell.classList.add("sel");
        if (errs.some(i => i.day === d && i.n === n)) cell.classList.add("bad");
        cell.onclick = () => selectLesson(l);
        cell.ondragstart = e => { e.dataTransfer.setData("text/plain", l.id); };
      }
      cell.ondragover = e => { e.preventDefault(); cell.classList.add("drop"); };
      cell.ondragleave = () => cell.classList.remove("drop");
      cell.ondrop = async e => {
        e.preventDefault();
        cell.classList.remove("drop");
        const id = Number(e.dataTransfer.getData("text/plain"));
        if (!id) return;
        S = await api("/api/move", { id, day: d, n });
        curLesson = S.model.lessons.find(x => x.id === id) || null;
        renderAll();
        toast("перенесено");
      };
      g.appendChild(cell);
    });
  }
}

function shortName(fio) {
  const p = fio.split(/\s+/);
  return p.length >= 3 ? `${p[0]} ${p[1][0]}.${p[2][0]}.` : fio;
}

function scoreOf(l) {
  return l.score ?? null;
}

// ---------- панель урока ----------
async function selectLesson(l) {
  curLesson = l;
  const box = $("#inspect");
  box.hidden = false;
  box.innerHTML = "";
  box.appendChild(el("h3", null, l.subject));
  box.appendChild(el("div", "muted", `${l.cls} · ${DAY_FULL[l.day]} · урок ${l.n}`));

  const cur = l.teacher ? teacherById(l.teacher) : null;
  box.appendChild(el("div", "muted", cur ? `Ведёт: ${cur.name}` : "Учитель не назначен"));

  const [free, sug] = await Promise.all([
    api(`/api/free?day=${l.day}&n=${l.n}&subject=${encodeURIComponent(l.subject)}`),
    api(`/api/suggest?cls=${encodeURIComponent(l.cls)}&subject=${encodeURIComponent(l.subject)}`),
  ]);

  const list = el("div", "who-list");
  const seen = new Set();
  const add = (t, tag) => {
    if (seen.has(t.id)) return;
    seen.add(t.id);
    const b = el("button", t.id === l.teacher ? "on" : "");
    b.appendChild(el("span", null, shortName(t.name)));
    if (tag) b.appendChild(el("div", "tag", tag));
    b.onclick = async () => {
      S = await api("/api/assign", { id: l.id, teacher: t.id === l.teacher ? null : t.id });
      curLesson = S.model.lessons.find(x => x.id === l.id);
      renderAll();
      selectLesson(curLesson);
    };
    list.appendChild(b);
  };
  sug.teachers.forEach(t => add(t, "вёл в прошлом году"));
  free.teachers.filter(t => t.teaches_subject).forEach(t => add(t, "предметник, свободен"));
  free.teachers.filter(t => !t.teaches_subject).slice(0, 25).forEach(t => add(t, `свободен · ${t.day_load} ур.`));
  box.appendChild(list);

  if (l.teacher) {
    const all = el("button", "btn");
    all.textContent = `Назначить на все «${l.subject}» в ${l.cls}`;
    all.onclick = async () => {
      S = await api("/api/assign-bulk", { cls: l.cls, subject: l.subject, teacher: l.teacher });
      renderAll();
      toast("назначено по всему предмету");
    };
    box.appendChild(all);
  }
  const close = el("button", "btn ghost", "Закрыть");
  close.style.marginTop = "8px";
  close.onclick = () => { box.hidden = true; curLesson = null; renderGrid(); };
  box.appendChild(close);
  renderGrid();
}

// ---------- учителя ----------
function renderTeacherList() {
  const q = ($("#tsearch").value || "").toLowerCase();
  const box = $("#teacher-list");
  box.className = "class-list rows";
  box.innerHTML = "";
  S.model.teachers
    .filter(t => !q || t.name.toLowerCase().includes(q))
    .forEach(t => {
      const b = el("button", t.id === curTeacher ? "on" : "", shortName(t.name));
      b.onclick = () => { curTeacher = t.id; renderTeacherList(); renderTeacherGrid(); };
      box.appendChild(b);
    });
}

function renderTeacherGrid() {
  const t = teacherById(curTeacher);
  if (!t) return;
  $("#tname").textContent = t.name;
  const mine = S.model.lessons.filter(l => l.teacher === t.id);
  const wins = S.analysis.windows.filter(w => w.teacher === t.id);
  $("#tmeta").textContent =
    `${t.subjects.join(", ") || "предмет не указан"} · ${mine.length} уроков в неделю` +
    (wins.length ? ` · окна: ${wins.map(w => `${w.day} (${w.gaps.join(",")})`).join(", ")}` : " · без окон");

  const g = $("#tgrid");
  g.innerHTML = "";
  g.style.gridTemplateColumns = `54px repeat(${DAYS.length}, minmax(0,1fr))`;
  g.appendChild(el("div", "cell head", ""));
  DAYS.forEach(d => g.appendChild(el("div", "cell head", DAY_FULL[d])));
  const rows = Math.max(maxLesson(mine), 7);
  for (let n = 1; n <= rows; n++) {
    g.appendChild(el("div", "cell num", String(n)));
    DAYS.forEach(d => {
      const here = mine.filter(l => l.day === d && l.n === n);
      const cell = el("div", "cell");
      here.forEach(l => {
        cell.appendChild(el("div", "subj", l.cls));
        cell.appendChild(el("div", "who", l.subject));
      });
      if (here.length > 1) cell.classList.add("bad");
      g.appendChild(cell);
    });
  }
}

// ---------- проверки ----------
function renderIssues() {
  const showErr = $("#f-error").checked, showWarn = $("#f-warn").checked;
  const box = $("#issues");
  box.innerHTML = "";
  const s = S.analysis.summary;
  const head = el("div", "muted");
  head.textContent = `${s.lessons} уроков · ${s.errors} нарушений · ${s.warnings} рекомендаций · ` +
                     `${s.unassigned} уроков без учителя`;
  box.appendChild(head);

  const groups = {};
  S.analysis.issues
    .filter(i => (i.level === "error" && showErr) || (i.level === "warn" && showWarn))
    .forEach(i => { (groups[i.rule] ||= []).push(i); });

  const titles = {
    week_load: "Недельная нагрузка", day_lessons: "Число уроков в день",
    day_share: "Распределение трудности по дням", hard_on_edge: "Трудные предметы с краю дня",
    teacher_clash: "Учитель в двух классах", room_clash: "Кабинет занят дважды",
    teacher_window: "Окна у учителей", double_primary: "Сдвоенные уроки в начальной школе",
    subject_thrice: "Один предмет трижды за день", no_score: "Предмет без балла трудности",
  };
  Object.entries(groups).forEach(([rule, items]) => {
    box.appendChild(el("div", "group-title", `${titles[rule] || rule} — ${items.length}`));
    items.forEach(i => {
      const row = el("div", "issue " + i.level);
      row.appendChild(el("div", "dot"));
      const txt = el("div", null, i.text);
      if (i.cls) {
        txt.style.cursor = "pointer";
        txt.onclick = () => { curClass = i.cls; showTab("grid"); renderClassList(); renderGrid(); };
      }
      row.appendChild(txt);
      row.appendChild(el("div", "src", i.source));
      box.appendChild(row);
    });
  });
  $("#badge").textContent = s.errors ? s.errors : "";
}

// ---------- замены ----------
async function renderDay() {
  const date = $("#subdate").value;
  if (!date) return;
  const sheet = await api(`/api/day?date=${date}`);
  const box = $("#daysheet");
  box.innerHTML = "";

  const line = $("#absent-line");
  line.innerHTML = "";
  sheet.absent.forEach(id => {
    const t = teacherById(id);
    const p = el("span", "pill", `${t ? shortName(t.name) : id} ✕`);
    p.title = "убрать отметку";
    p.onclick = async () => {
      await api("/api/absence", { date, teacher: id, remove: true });
      renderDay();
    };
    line.appendChild(p);
  });

  if (!sheet.day) {
    box.appendChild(el("p", "muted", "Выходной — уроков нет."));
    return;
  }
  const affected = sheet.rows.filter(r => r.absent);
  const title = el("div", "muted",
    `${sheet.day_full}, ${date} · уроков ${sheet.rows.length}` +
    (affected.length ? ` · требуют замены ${affected.length}` : ""));
  box.appendChild(title);

  const table = el("table");
  table.innerHTML = "<thead><tr><th>Класс</th><th class='num'>Урок</th><th>Предмет</th>" +
                    "<th>Учитель</th><th>Замена</th><th></th></tr></thead>";
  const tb = el("tbody");
  const rows = affected.length ? affected : sheet.rows;
  rows.forEach(r => {
    const tr = el("tr", r.absent ? "absent" : "");
    tr.appendChild(el("td", null, r.cls));
    tr.appendChild(el("td", "num", String(r.n)));
    tr.appendChild(el("td", null, r.subject));
    tr.appendChild(el("td", null, r.teacher_name || "—"));
    const td = el("td");
    if (r.replacement) {
      td.appendChild(el("span", "pill done", `${r.replacement_name || r.replacement.to} · ${r.replacement.kind}`));
    } else if (r.absent) {
      td.appendChild(el("span", "pill need", "нужна замена"));
    }
    tr.appendChild(td);
    const act = el("td");
    if (r.absent) {
      const b = el("button", "btn", r.replacement ? "изменить" : "подобрать");
      b.onclick = () => pickReplacement(date, r);
      act.appendChild(b);
    }
    tr.appendChild(act);
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  box.appendChild(table);
}

async function pickReplacement(date, row) {
  const free = await api(`/api/free?day=${row.day}&n=${row.n}&subject=${encodeURIComponent(row.subject)}`);
  const box = $("#daysheet");
  const panel = el("div", "pane");
  panel.style.marginTop = "14px";
  panel.appendChild(el("h2", null, `Кто заменит: ${row.cls}, урок ${row.n}, ${row.subject}`));
  panel.appendChild(el("div", "muted", "Сначала предметники, затем свободные по нагрузке дня."));
  const list = el("div", "who-list");
  list.style.maxHeight = "260px";
  free.teachers.slice(0, 30).forEach(t => {
    const b = el("button");
    b.textContent = `${shortName(t.name)} — ${t.teaches_subject ? "ведёт предмет" : t.subjects.join(", ") || "—"} · ${t.day_load} ур.`;
    b.onclick = async () => {
      await api("/api/substitute", { date, cls: row.cls, day: row.day, n: row.n,
                                     subject: row.subject, from: row.teacher, to: t.id,
                                     kind: "замена" });
      panel.remove();
      renderDay();
      toast("замена записана");
    };
    list.appendChild(b);
  });
  panel.appendChild(list);
  const cancel = el("button", "btn ghost", "Отмена");
  cancel.onclick = () => panel.remove();
  panel.appendChild(cancel);
  box.appendChild(panel);
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- баллы ----------
function renderScores() {
  const box = $("#scores");
  box.innerHTML = "";
  const subjects = [...new Set(S.model.lessons.map(l => l.subject))].sort();
  const grades = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
  const table = el("table");
  table.innerHTML = "<thead><tr><th>Предмет</th>" +
    grades.map(g => `<th class='num'>${g}</th>`).join("") + "</tr></thead>";
  const tb = el("tbody");
  subjects.forEach(sub => {
    const tr = el("tr");
    tr.appendChild(el("td", null, sub));
    grades.forEach(g => {
      const td = el("td", "num");
      const used = S.model.lessons.some(l => l.subject === sub && gradeOf(l.cls) === g);
      if (used) {
        const inp = el("input", "scores-edit");
        inp.type = "number"; inp.min = "0"; inp.max = "20";
        const key = sub.toLowerCase();
        const own = (S.scores[key] || {})[String(g)];
        inp.value = own ?? (scoreLookup(sub, g) ?? "");
        if (own != null) inp.classList.add("set");
        inp.onchange = async () => {
          const scores = JSON.parse(JSON.stringify(S.scores));
          scores[key] ||= {};
          if (inp.value === "") delete scores[key][String(g)];
          else scores[key][String(g)] = Number(inp.value);
          if (!Object.keys(scores[key]).length) delete scores[key];
          S = await api("/api/scores", { scores });
          renderAll();
          toast("балл сохранён");
        };
        td.appendChild(inp);
      } else {
        td.appendChild(el("span", "muted", "·"));
      }
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  box.appendChild(table);
}

function scoreLookup(subject, grade) {
  const l = S.model.lessons.find(x => x.subject === subject && gradeOf(x.cls) === grade);
  return l ? (l.score_file ?? null) : null;
}


// ---------- конструктор ----------
async function runBuild() {
  const btn = $("#gen-run");
  const box = $("#gen-result");
  const seconds = Number($("#gen-seconds").value);
  btn.disabled = true;
  btn.textContent = "Считаю…";
  box.innerHTML = "";
  const started = Date.now();
  const tick = setInterval(() => {
    const left = Math.max(0, seconds - Math.round((Date.now() - started) / 1000));
    btn.textContent = left ? `Считаю… ${left} с` : "Почти готово…";
  }, 1000);
  try {
    const res = await api("/api/generate", { seconds, attempts: Number($("#gen-attempts").value) });
    renderBuildResult(res);
  } finally {
    clearInterval(tick);
    btn.disabled = false;
    btn.textContent = "Собрать";
  }
}

function renderBuildResult(res) {
  const box = $("#gen-result");
  box.innerHTML = "";
  const a = res.analysis.summary, b = res.before, r = res.report;

  const cmp = el("div", "daybars");
  const card = (title, was, now, better) => {
    const d = el("div", "daybar " + (now === was ? "" : better ? "ok" : "off"));
    d.appendChild(el("b", null, title));
    d.appendChild(el("div", "v", String(now)));
    d.appendChild(el("div", "s", was === now ? "без изменений" : `было ${was}`));
    return d;
  };
  cmp.appendChild(card("нарушений", b.errors, a.errors, a.errors <= b.errors));
  cmp.appendChild(card("рекомендаций", b.warnings, a.warnings, a.warnings <= b.warnings));
  cmp.appendChild(card("накладок учителей", "—", r.clashes, r.clashes === 0));
  cmp.appendChild(card("окон у учителей", "—", r.windows, true));
  if (r.prefs_total) cmp.appendChild(card("пожеланий учтено", r.prefs_total, r.prefs_ok, true));
  const t = el("div", "daybar");
  t.appendChild(el("b", null, "расчёт"));
  t.appendChild(el("div", "v", `${r.seconds} с`));
  t.appendChild(el("div", "s", `${r.steps.toLocaleString("ru")} перестановок`));
  cmp.appendChild(t);
  box.appendChild(cmp);

  const row = el("div", "row");
  row.style.margin = "14px 0";
  const apply = el("button", "btn");
  apply.textContent = `Применить — ${r.lessons} уроков`;
  apply.onclick = async () => {
    S = await api("/api/apply", {});
    renderAll();
    showTab("grid");
    toast("расписание применено, прежнее — в data/backups");
  };
  const again = el("button", "btn ghost", "Пересобрать");
  again.onclick = runBuild;
  row.appendChild(apply);
  row.appendChild(again);
  box.appendChild(row);

  if (res.analysis.issues.length) {
    box.appendChild(el("div", "group-title", "Что осталось в новом варианте"));
    const groups = {};
    res.analysis.issues.forEach(i => { (groups[i.rule] ||= []).push(i); });
    Object.entries(groups).forEach(([rule, items]) => {
      const d = el("div", "issue " + items[0].level);
      d.appendChild(el("div", "dot"));
      d.appendChild(el("div", null, `${items[0].text}${items.length > 1 ? ` — и ещё ${items.length - 1}` : ""}`));
      d.appendChild(el("div", "src", items[0].source));
      box.appendChild(d);
    });
  }
}

// ---------- нагрузка и пожелания ----------
function renderPlan() {
  const box = $("#plan-box");
  box.innerHTML = "";
  const withoutTeacher = S.plan.filter(r => !r.teacher).length;
  box.appendChild(el("div", "muted",
    `${S.plan.length} позиций плана · ${withoutTeacher} без учителя · ` +
    `${S.model.lessons.length} уроков в неделю`));

  const table = el("table");
  table.innerHTML = "<thead><tr><th>Класс</th><th>Предмет</th><th class='num'>Часов</th>" +
                    "<th>Учитель</th></tr></thead>";
  const tb = el("tbody");
  S.plan.forEach(r => {
    const tr = el("tr");
    tr.appendChild(el("td", null, r.cls));
    tr.appendChild(el("td", null, r.subject));
    const th = el("td", "num");
    const inp = el("input", "scores-edit");
    inp.type = "number"; inp.min = "0"; inp.max = "12"; inp.value = r.hours;
    inp.onchange = async () => {
      S = await api("/api/plan/hours", { cls: r.cls, subject: r.subject, hours: Number(inp.value) });
      renderAll(); renderPlan(); toast("часы изменены");
    };
    th.appendChild(inp);
    tr.appendChild(th);

    const td = el("td");
    const sel = el("select");
    sel.style.maxWidth = "260px";
    const none = el("option", null, "— не назначен —");
    none.value = "";
    sel.appendChild(none);
    S.model.teachers.forEach(t => {
      const o = el("option", null, shortName(t.name) + (t.subjects.length ? ` · ${t.subjects[0]}` : ""));
      o.value = t.id;
      if (t.id === r.teacher) o.selected = true;
      sel.appendChild(o);
    });
    if (!r.teacher) sel.style.borderColor = "var(--red)";
    sel.onchange = async () => {
      S = await api("/api/plan/teacher", { cls: r.cls, subject: r.subject, teacher: sel.value });
      renderAll(); renderPlan(); toast("учитель назначен");
    };
    td.appendChild(sel);
    tr.appendChild(td);
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  box.appendChild(table);
}

const PREF_KINDS = {
  no_day: "не ставить в день",
  max_per_day: "не больше уроков в день",
  free_day: "нужен свободный день",
  early: "ставить не позже урока",
};

function renderPrefs() {
  const box = $("#prefs-box");
  box.innerHTML = "";
  if (!S.prefs.length) {
    box.appendChild(el("div", "muted", "Пожеланий пока нет — конструктор учитывает только нормативы."));
    return;
  }
  const table = el("table");
  table.innerHTML = "<thead><tr><th>Учитель</th><th>Пожелание</th><th>Значение</th>" +
                    "<th>Обязательно</th><th></th></tr></thead>";
  const tb = el("tbody");
  S.prefs.forEach((p, idx) => {
    const t = teacherById(p.teacher);
    const tr = el("tr");
    tr.appendChild(el("td", null, t ? shortName(t.name) : p.teacher));
    tr.appendChild(el("td", null, PREF_KINDS[p.kind] || p.kind));
    tr.appendChild(el("td", null, p.day ? DAY_FULL[p.day] : String(p.value ?? "")));
    tr.appendChild(el("td", null, p.hard ? "да" : "желательно"));
    const td = el("td");
    const del = el("button", "btn ghost", "убрать");
    del.onclick = async () => {
      const prefs = S.prefs.filter((_, i) => i !== idx);
      S = await api("/api/prefs", { prefs });
      renderPrefs(); toast("пожелание убрано");
    };
    td.appendChild(del);
    tr.appendChild(td);
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  box.appendChild(table);
}

function addPref() {
  const box = $("#prefs-box");
  const form = el("div", "pane");
  form.style.margin = "0 0 14px";
  form.appendChild(el("h2", null, "Новое пожелание"));
  const row = el("div", "row");

  const who = el("select");
  S.model.teachers.forEach(t => {
    const o = el("option", null, shortName(t.name));
    o.value = t.id;
    who.appendChild(o);
  });
  const kind = el("select");
  Object.entries(PREF_KINDS).forEach(([k, label]) => {
    const o = el("option", null, label);
    o.value = k;
    kind.appendChild(o);
  });
  const dayPick = el("select");
  DAYS.forEach(d => {
    const o = el("option", null, DAY_FULL[d]);
    o.value = d;
    dayPick.appendChild(o);
  });
  const val = el("input", "scores-edit");
  val.type = "number"; val.min = "1"; val.max = "7"; val.value = "4";
  const hard = el("label", "muted");
  const chk = el("input");
  chk.type = "checkbox";
  hard.appendChild(chk);
  hard.appendChild(document.createTextNode(" обязательно"));

  const sync = () => {
    dayPick.hidden = kind.value !== "no_day";
    val.hidden = !["max_per_day", "early"].includes(kind.value);
  };
  kind.onchange = sync;
  sync();

  const save = el("button", "btn", "Сохранить");
  save.onclick = async () => {
    const p = { teacher: who.value, kind: kind.value, hard: chk.checked };
    if (kind.value === "no_day") p.day = dayPick.value;
    if (["max_per_day", "early"].includes(kind.value)) p.value = Number(val.value);
    S = await api("/api/prefs", { prefs: [...S.prefs, p] });
    form.remove();
    renderPrefs();
    toast("пожелание добавлено");
  };
  const cancel = el("button", "btn ghost", "Отмена");
  cancel.onclick = () => form.remove();

  [who, kind, dayPick, val, hard, save, cancel].forEach(n => row.appendChild(n));
  form.appendChild(row);
  box.prepend(form);
}

// ---------- общее ----------
function showTab(name) {
  $$(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("on", t.id === "tab-" + name));
  if (name === "checks") renderIssues();
  if (name === "teachers") { renderTeacherList(); renderTeacherGrid(); }
  if (name === "subs") renderDay();
  if (name === "scores") renderScores();
  if (name === "load") { renderPrefs(); renderPlan(); }
}

function renderAll() {
  $("#year").textContent = S.model.meta.year || "";
  $("#saved").textContent = S.model.meta.saved_at
    ? "сохранено " + S.model.meta.saved_at.replace("T", " ").slice(5, 16) : "";
  renderClassList();
  renderGrid();
  renderIssues();
  const pick = $("#absent-pick");
  if (pick.options.length <= 1) {
    S.model.teachers.forEach(t => {
      const o = el("option", null, `${shortName(t.name)} — ${t.subjects.join(", ")}`);
      o.value = t.id;
      pick.appendChild(o);
    });
  }
}

async function boot() {
  S = await api("/api/state");
  curClass = S.model.classes.length ? S.model.classes[0].id : null;
  $("#subdate").value = new Date().toISOString().slice(0, 10);
  $$(".tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
  $("#f-error").onchange = renderIssues;
  $("#f-warn").onchange = renderIssues;
  $("#tsearch").oninput = renderTeacherList;
  $("#subdate").onchange = renderDay;
  $("#add-absent").onclick = async () => {
    const id = $("#absent-pick").value;
    if (!id) return toast("выберите учителя");
    await api("/api/absence", { date: $("#subdate").value, teacher: id });
    renderDay();
  };
  $("#print-day").onclick = () => window.print();
  $("#gen-run").onclick = runBuild;
  $("#auto-assign").onclick = async () => {
    const res = await api("/api/plan/autoassign", {});
    S = res;
    renderAll(); renderPlan();
    toast(`назначено: ${res.autoassign.homeroom} по классным руководителям, ` +
          `${res.autoassign.prior} по прошлому году`);
  };
  $("#add-pref").onclick = addPref;
  renderAll();
}

boot();
