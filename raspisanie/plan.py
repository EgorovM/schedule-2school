# -*- coding: utf-8 -*-
"""Учебный план и нагрузка: сколько часов какого предмета в классе и кто ведёт.

План выводится из расписания: сколько раз предмет встречается за неделю —
столько часов в нём и есть. Дальше завуч правит часы руками, а конструктор
раскладывает уроки по этому плану.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import sanpin

CLASS_RE = re.compile(r"\b(\d{1,2})\s*([а-дА-Д])\b")


def _grade(cls: str) -> int:
    m = re.match(r"\d+", cls)
    return int(m.group()) if m else 0


def homeroom_of(teacher: dict) -> str | None:
    """«учитель нач классов 2б» → '2б'. В справочнике классных руководителей
    начальной школы класс записан прямо в графе предмета."""
    text = " ".join(teacher.get("subjects", [])).lower()
    if "нач" not in text and "клас" not in text:
        return None
    m = CLASS_RE.search(text)
    return f"{m.group(1)}{m.group(2).lower()}" if m else None


def build(model: dict) -> list[dict]:
    """Учебный план: по одной строке на пару «класс + предмет»."""
    hours = Counter()
    teachers = defaultdict(Counter)
    rooms = defaultdict(Counter)
    for l in model["lessons"]:
        key = (l["cls"], l["subject"])
        hours[key] += 1
        if l.get("teacher"):
            teachers[key][l["teacher"]] += 1
        if l.get("room"):
            rooms[key][l["room"]] += 1

    order = {c["id"]: i for i, c in enumerate(model["classes"])}
    rows = []
    for (cls, subject), h in hours.items():
        chosen = teachers[key] if False else teachers[(cls, subject)]
        rows.append({
            "cls": cls,
            "subject": subject,
            "hours": h,
            "teacher": chosen.most_common(1)[0][0] if chosen else None,
            "room": rooms[(cls, subject)].most_common(1)[0][0] if rooms[(cls, subject)] else None,
            "split": len(chosen) > 1,      # предмет ведут в подгруппах
        })
    rows.sort(key=lambda r: (order.get(r["cls"], 99), -r["hours"], r["subject"]))
    return rows


# Сотрудники, которые уроков не ведут и в расстановку попадать не должны.
NOT_TEACHING = ("тьютор", "психолог", "логопед", "дефектолог", "домобучение",
                "библиот", "социальн", "вожат", "советник")

MAX_HOURS = 30          # разумный потолок недельной нагрузки при автораспределении


def _teaches(teacher: dict, subject: str) -> bool:
    text = " ".join(teacher.get("subjects", [])).lower()
    if any(w in text for w in NOT_TEACHING):
        return False
    want = sanpin.normalize(subject)
    for part in re.split(r"[,;]", text):
        if not part.strip():
            continue
        if sanpin.normalize(part) == want:
            return True
    return False


def autoassign(model: dict, max_hours: int = MAX_HOURS) -> dict:
    """Распределяет учителей по учебному плану.

    1) классный руководитель 1—4 класса ведёт все предметы своего класса;
    2) остальные позиции раздаются предметникам с балансировкой нагрузки:
       параллельные классы достаются разным учителям, а не одному, потому что
       у параллели один и тот же предмет часто стоит в один и тот же час.
       Подсказка по прошлогодней расстановке повышает приоритет кандидата.
    """
    from .rules import suggest_teacher

    homerooms = {}
    for t in model["teachers"]:
        cls = homeroom_of(t)
        if cls:
            homerooms[cls] = t["id"]

    by_id = {t["id"]: t for t in model["teachers"]}
    hours = Counter()
    for l in model["lessons"]:
        if l.get("teacher"):
            hours[l["teacher"]] += 1

    rows = [r for r in build(model) if not r["teacher"]]
    filled_home = 0
    assign: dict[tuple[str, str], str] = {}

    for row in rows:
        cls = row["cls"]
        if _grade(cls) <= 4 and cls in homerooms:
            assign[(cls, row["subject"])] = homerooms[cls]
            hours[homerooms[cls]] += row["hours"]
            filled_home += 1

    rest = [r for r in rows if (r["cls"], r["subject"]) not in assign]

    # кандидаты на каждую позицию: подсказка прошлого года плюс предметники
    options = {}
    for row in rest:
        key = (row["cls"], row["subject"])
        weights = Counter()
        for s in suggest_teacher(model, row["cls"], row["subject"]):
            if by_id.get(s["id"]) and _teaches_or_unknown(by_id[s["id"]], row["subject"]):
                weights[s["id"]] += 10 * s["weight"]
        for t in model["teachers"]:
            if _teaches(t, row["subject"]):
                weights[t["id"]] += 5
        options[key] = weights

    # сначала позиции с наименьшим выбором — им труднее найти замену
    rest.sort(key=lambda r: (len(options[(r["cls"], r["subject"])]), -r["hours"]))

    filled = 0
    for row in rest:
        key = (row["cls"], row["subject"])
        weights = options[key]
        if not weights:
            continue
        # среди кандидатов берём того, кто свободнее: вес подсказки минус нагрузка
        best = max(weights,
                   key=lambda tid: (weights[tid] - hours[tid] * 2,
                                    -hours[tid]))
        if hours[best] + row["hours"] > max_hours:
            relaxed = [t for t in weights if hours[t] + row["hours"] <= max_hours]
            if relaxed:
                best = max(relaxed, key=lambda tid: weights[tid] - hours[tid] * 2)
        assign[key] = best
        hours[best] += row["hours"]
        filled += 1

    for l in model["lessons"]:
        if not l.get("teacher"):
            tid = assign.get((l["cls"], l["subject"]))
            if tid:
                l["teacher"] = tid

    return {"homeroom": filled_home, "prior": filled,
            "left": sum(1 for l in model["lessons"] if not l.get("teacher")),
            "max_hours": max(hours.values()) if hours else 0}


def _teaches_or_unknown(teacher: dict, subject: str) -> bool:
    """Кандидат годится, если ведёт предмет или его специализация не указана."""
    text = " ".join(teacher.get("subjects", [])).lower()
    if any(w in text for w in NOT_TEACHING):
        return False
    return True


def teacher_load(model: dict) -> list[dict]:
    """Нагрузка каждого педагога: часы, классы, предметы."""
    per = defaultdict(lambda: {"hours": 0, "classes": set(), "subjects": set()})
    for l in model["lessons"]:
        if not l.get("teacher"):
            continue
        p = per[l["teacher"]]
        p["hours"] += 1
        p["classes"].add(l["cls"])
        p["subjects"].add(l["subject"])
    out = []
    for t in model["teachers"]:
        p = per.get(t["id"])
        out.append({"id": t["id"], "name": t["name"], "code": t["code"],
                    "hours": p["hours"] if p else 0,
                    "classes": sorted(p["classes"]) if p else [],
                    "subjects": sorted(p["subjects"]) if p else []})
    out.sort(key=lambda t: -t["hours"])
    return out


def unassigned(model: dict) -> list[dict]:
    """Позиции плана без учителя — их конструктор поставить не сможет."""
    return [r for r in build(model) if not r["teacher"]]
