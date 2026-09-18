# -*- coding: utf-8 -*-
"""Проверка расписания: нормы СанПиН и организационные накладки.

Каждое нарушение несёт ссылку на источник, чтобы завуч мог проверить требование.
level: error — нарушение норматива; warn — отступление от рекомендации.
"""
from __future__ import annotations

from collections import defaultdict

from . import sanpin

SRC_SANPIN = "СанПиН 1.2.3685-21, табл. 6.6"
SRC_SCALE = "СанПиН 1.2.3685-21, табл. 6.9—6.11"
SRC_MR = "МР 2.4.0331-23, п. 3.2"
SRC_SP = "СП 2.4.3648-20"


def is_extracurricular(subject: str) -> bool:
    """Внеурочная деятельность в предельную аудиторную нагрузку не входит
    (СанПиН 1.2.3685-21, табл. 6.6: недельный объём внеурочной — отдельная норма, до 10 ч)."""
    s = subject.lower()
    return s.startswith("вуд") or "внеурочн" in s


def _grade(cls: str) -> int:
    import re
    m = re.match(r"\d+", cls)
    return int(m.group()) if m else 0


def score_of(lesson: dict, grade: int, overrides: dict | None) -> int | None:
    """Балл трудности: приоритет у школьной таблицы, иначе СанПиН."""
    s = sanpin.difficulty(lesson["subject"], grade, overrides)
    if s is None:
        s = lesson.get("score_file")
    return s


def analyze(model: dict, overrides: dict | None = None) -> dict:
    lessons = model["lessons"]
    classes = {c["id"]: c for c in model["classes"]}
    teachers = {t["id"]: t for t in model["teachers"]}
    issues: list[dict] = []

    by_class = defaultdict(list)
    by_slot = defaultdict(list)
    for l in lessons:
        by_class[l["cls"]].append(l)
        by_slot[(classes.get(l["cls"], {}).get("shift", 1), l["day"], l["n"])].append(l)

    # ---- баллы и суммы по дням --------------------------------------------
    stats = {}
    for cls, items in by_class.items():
        grade = _grade(cls)
        days = defaultdict(lambda: {"count": 0, "score": 0, "unscored": 0})
        extra = 0
        for l in items:
            if is_extracurricular(l["subject"]):
                extra += 1
                continue
            sc = score_of(l, grade, overrides)
            d = days[l["day"]]
            d["count"] += 1
            if sc is None:
                d["unscored"] += 1
            else:
                d["score"] += sc
        total = sum(d["score"] for d in days.values())
        week_days = classes.get(cls, {}).get("days", 6)
        limits = sanpin.DAY_SHARE.get(week_days, sanpin.DAY_SHARE[6])
        shares = {}
        for day, d in days.items():
            share = round(d["score"] / total * 100, 1) if total else 0
            fits = []
            for variant, table in limits.items():
                lo, hi = table.get(day, (0, 100))
                if lo <= share <= hi:
                    fits.append(variant)
            shares[day] = {"share": share, "fits": fits, **d}
        stats[cls] = {"total": total, "days": shares, "extra": extra,
                      "week": sum(d["count"] for d in days.values())}

        # недельная нагрузка
        limit = sanpin.max_week(grade, week_days)
        week_hours = stats[cls]["week"]
        if limit and week_hours > limit:
            issues.append({"level": "error", "rule": "week_load", "cls": cls,
                           "text": f"{cls}: {week_hours} уроков в неделю при норме не более {limit}",
                           "source": SRC_SANPIN})

        # уроков в день
        md = sanpin.max_day(grade)
        over = [(day, d["count"]) for day, d in days.items() if d["count"] > md["norm"]]
        for day, cnt in over:
            if cnt > md["relief"]:
                text = (f"{cls}, {sanpin.DAY_FULL[day]}: {cnt} уроков — "
                        f"больше предельных {md['relief']}")
                level = "error"
            elif len(over) == 1:
                continue    # ровно один облегчённый-наоборот день допускается
            else:
                text = (f"{cls}, {sanpin.DAY_FULL[day]}: {cnt} уроков при норме {md['norm']}; "
                        f"{md['relief']} уроков допускается только один раз в неделю, "
                        f"а таких дней {len(over)}")
                level = "error"
            issues.append({"level": level, "rule": "day_lessons", "cls": cls, "day": day,
                           "text": text, "source": SRC_SANPIN})

        # распределение трудности по дням
        for day, d in shares.items():
            if not d["fits"] and total:
                v1 = limits[1].get(day, (0, 100))
                miss = min(abs(d["share"] - b)
                           for var in limits.values()
                           for b in var.get(day, (0, 100)))
                if miss < 2.0:
                    continue   # мелкое отклонение видно в таблице, в список не выносим
                issues.append({"level": "warn", "rule": "day_share", "cls": cls, "day": day,
                               "text": f"{cls}, {sanpin.DAY_FULL[day]}: {d['share']}% недельной "
                                       f"трудности — вне обоих вариантов распределения "
                                       f"(вариант 1: {v1[0]}—{v1[1]}%)",
                               "source": SRC_MR})

        # предметы без норматива трудности
        unscored = sorted({l["subject"] for l in items
                           if score_of(l, grade, overrides) is None})
        for subj in unscored:
            issues.append({"level": "warn", "rule": "no_score", "cls": cls,
                           "text": f"{cls}: для предмета «{subj}» не задан балл трудности",
                           "source": SRC_SCALE})

        # самый трудный предмет дня — первым или последним уроком
        for day in days:
            day_lessons = sorted([l for l in items if l["day"] == day], key=lambda x: x["n"])
            if len(day_lessons) < 3:
                continue
            scored = [(l, score_of(l, grade, overrides)) for l in day_lessons]
            scored = [(l, s) for l, s in scored if s is not None]
            if not scored:
                continue
            top = max(s for _, s in scored)
            edges = [l for l, s in scored if s == top and
                     (l["n"] == day_lessons[0]["n"] or l["n"] == day_lessons[-1]["n"])]
            middle_max = max([s for l, s in scored
                              if day_lessons[0]["n"] < l["n"] < day_lessons[-1]["n"]] or [0])
            for l in edges:
                if top > middle_max:
                    issues.append({"level": "warn", "rule": "hard_on_edge", "cls": cls,
                                   "day": day, "n": l["n"],
                                   "text": f"{cls}, {sanpin.DAY_FULL[day]}, урок {l['n']}: "
                                           f"«{l['subject']}» — самый трудный предмет дня "
                                           f"({top} б.) стоит с краю",
                                   "source": SRC_MR})

        # сдвоенные уроки в начальной школе
        if grade in sanpin.DOUBLE_LESSONS_BANNED_GRADES:
            for day in days:
                seq = sorted([l for l in items if l["day"] == day], key=lambda x: x["n"])
                for a, b in zip(seq, seq[1:]):
                    if a["subject"] == b["subject"] and b["n"] == a["n"] + 1 \
                            and "физическая" not in a["subject"].lower():
                        issues.append({"level": "error", "rule": "double_primary", "cls": cls,
                                       "day": day, "n": a["n"],
                                       "text": f"{cls}, {sanpin.DAY_FULL[day]}, уроки "
                                               f"{a['n']}—{b['n']}: сдвоенный «{a['subject']}» "
                                               f"в начальной школе",
                                       "source": SRC_SANPIN})

        # один предмет три и более раз в день
        for day in days:
            cnt = defaultdict(int)
            for l in items:
                if l["day"] == day:
                    cnt[l["subject"]] += 1
            for subj, k in cnt.items():
                if k >= 3:
                    issues.append({"level": "warn", "rule": "subject_thrice", "cls": cls,
                                   "day": day,
                                   "text": f"{cls}, {sanpin.DAY_FULL[day]}: «{subj}» {k} раза за день",
                                   "source": SRC_MR})

    # ---- накладки учителей и кабинетов ------------------------------------
    teacher_slots = defaultdict(list)
    room_slots = defaultdict(list)
    for l in lessons:
        shift = classes.get(l["cls"], {}).get("shift", 1)
        if l.get("teacher"):
            teacher_slots[(l["teacher"], l["day"], l["n"], shift)].append(l)
        if l.get("room"):
            room_slots[(l["room"], l["day"], l["n"], shift)].append(l)

    for (tid, day, n, _), items in teacher_slots.items():
        if len(items) > 1:
            name = teachers.get(tid, {}).get("name", tid)
            issues.append({"level": "error", "rule": "teacher_clash", "teacher": tid,
                           "day": day, "n": n,
                           "text": f"{name}: {sanpin.DAY_FULL[day]}, урок {n} — "
                                   f"одновременно {', '.join(i['cls'] for i in items)}",
                           "source": "организационное"})
    for (room, day, n, _), items in room_slots.items():
        if len({i["cls"] for i in items}) > 1:
            issues.append({"level": "error", "rule": "room_clash", "day": day, "n": n,
                           "text": f"Кабинет {room}: {sanpin.DAY_FULL[day]}, урок {n} — "
                                   f"{', '.join(sorted({i['cls'] for i in items}))}",
                           "source": "организационное"})

    # окна у учителей
    windows = []
    per_teacher = defaultdict(lambda: defaultdict(list))
    for l in lessons:
        if l.get("teacher"):
            per_teacher[l["teacher"]][l["day"]].append(l["n"])
    for tid, days in per_teacher.items():
        for day, nums in days.items():
            nums = sorted(set(nums))
            gaps = [n for n in range(nums[0], nums[-1]) if n not in nums]
            if gaps:
                name = teachers.get(tid, {}).get("name", tid)
                windows.append({"teacher": tid, "day": day, "gaps": gaps})
                issues.append({"level": "warn", "rule": "teacher_window", "teacher": tid,
                               "day": day,
                               "text": f"{name}: {sanpin.DAY_FULL[day]} — окно на уроках "
                                       f"{', '.join(map(str, gaps))}",
                               "source": "организационное"})

    unassigned = sum(1 for l in lessons if not l.get("teacher"))
    order = {"error": 0, "warn": 1}
    issues.sort(key=lambda i: (order[i["level"]], i["rule"], i.get("cls", ""), i.get("day", "")))
    return {
        "issues": issues,
        "stats": stats,
        "windows": windows,
        "summary": {
            "errors": sum(1 for i in issues if i["level"] == "error"),
            "warnings": sum(1 for i in issues if i["level"] == "warn"),
            "lessons": len(lessons),
            "unassigned": unassigned,
        },
    }


def free_teachers(model: dict, day: str, n: int, subject: str | None = None,
                  exclude: set[str] | None = None) -> list[dict]:
    """Кто свободен в этот час. Сначала предметники, потом остальные."""
    classes = {c["id"]: c for c in model["classes"]}
    busy = set()
    for l in model["lessons"]:
        if l["day"] == day and l["n"] == n and l.get("teacher"):
            busy.add(l["teacher"])
    load = defaultdict(int)
    for l in model["lessons"]:
        if l["day"] == day and l.get("teacher"):
            load[l["teacher"]] += 1

    subj = sanpin.normalize(subject) if subject else None
    out = []
    for t in model["teachers"]:
        if t["id"] in busy or (exclude and t["id"] in exclude):
            continue
        teaches = any(sanpin.normalize(s) == subj for s in t.get("subjects", [])) if subj else False
        out.append({**t, "teaches_subject": teaches, "day_load": load.get(t["id"], 0)})
    out.sort(key=lambda t: (not t["teaches_subject"], t["day_load"], t["name"]))
    return out


def suggest_teacher(model: dict, cls: str, subject: str) -> list[dict]:
    """Подсказка по прошлогодней расстановке: кто вёл этот предмет в этом классе."""
    import re
    teachers = {t["id"]: t for t in model["teachers"]}
    grade = _grade(cls)
    letter = cls[len(str(grade)):]
    want = sanpin.normalize(subject)
    hits = defaultdict(int)
    for p in model.get("prior", []):
        if sanpin.normalize(p["subject"]) != want:
            continue
        pg = _grade(p["cls"])
        pl = p["cls"][len(str(pg)):]
        if p["cls"] == cls:
            weight = 3
        elif pg == grade - 1 and pl == letter:
            weight = 2      # тот же класс годом раньше
        elif pg == grade:
            weight = 1
        else:
            continue
        for tid in p["ids"]:
            hits[tid] += weight
    out = [{**teachers[t], "weight": w} for t, w in hits.items() if t in teachers]
    out.sort(key=lambda t: -t["weight"])
    return out[:5]
