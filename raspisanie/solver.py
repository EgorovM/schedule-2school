# -*- coding: utf-8 -*-
"""Конструктор расписания: раскладывает учебный план по дням и урокам.

Задача относится к классу труднорешаемых: точного быстрого метода нет, поэтому
работа идёт в два приёма. Сначала жадная расстановка даёт допустимое
расписание, затем локальный поиск с отжигом обменивает уроки местами, пока
сумма штрафов падает. Жёсткие требования (накладки учителей) входят в ту же
сумму с большим весом, чтобы поиск мог временно их допускать и выбираться из
тупиков.
"""
from __future__ import annotations

import math
import random
import re
import time
from collections import Counter, defaultdict

from . import plan as planner
from . import rules, sanpin

# Веса штрафов. Первые три — по сути жёсткие требования.
W_TEACHER_CLASH = 10000
W_ROOM_CLASH = 4000
W_DOUBLE_PRIMARY = 3000
W_PREF_HARD = 2000          # нарушено пожелание, отмеченное как обязательное
W_DAY_SHARE = 60            # за каждый процентный пункт вне нормы МР
W_HARD_EDGE = 40            # трудный предмет первым или последним уроком
W_SUBJECT_TWICE = 35        # предмет дважды за день
W_SUBJECT_THRICE = 400
W_TEACHER_WINDOW = 25       # окно у учителя
W_TEACHER_ONE = 15          # день, ради которого учитель приходит на один урок
W_PREF_SOFT = 120           # нарушено пожелание-предпочтение
W_PE_LAST = 0               # физкультура последним уроком — нормой не запрещена
W_DAY_OVER = 1500           # уроков в день больше, чем разрешает СанПиН


def _grade(cls: str) -> int:
    m = re.match(r"\d+", cls)
    return int(m.group()) if m else 0


class Builder:
    def __init__(self, model: dict, scores: dict | None = None,
                 prefs: list | None = None, options: dict | None = None):
        self.model = model
        self.scores = scores or {}
        self.prefs = prefs or []
        self.opt = options or {}
        self.rnd = random.Random(self.opt.get("seed", 20262027))

        self.classes = {c["id"]: c for c in model["classes"]}
        self.teachers = {t["id"]: t for t in model["teachers"]}

        # предметы, которые нельзя двигать (закреплённые завучем)
        self.pinned = set(self.opt.get("pinned", []))

        # уроки: список словарей с полями cls/subject/teacher/room + day/n
        self.lessons: list[dict] = []
        self.by_class: dict[str, list[dict]] = defaultdict(list)
        self.day_len: dict[tuple[str, str], int] = {}

        self._prepare()

    # ---------- подготовка ----------
    def _days_of(self, cls: str) -> list[str]:
        n = self.classes[cls].get("days", 6)
        return sanpin.DAYS[:n]

    def _score(self, cls: str, subject: str) -> int:
        if rules.is_extracurricular(subject):
            return 0
        return sanpin.difficulty(subject, _grade(cls), self.scores) or 0

    def _prepare(self) -> None:
        """Строит список уроков из учебного плана и раскладывает длины дней."""
        for row in planner.build(self.model):
            for _ in range(row["hours"]):
                self.lessons.append({
                    "cls": row["cls"], "subject": row["subject"],
                    "teacher": row["teacher"], "room": row["room"],
                    "day": None, "n": None,
                    "score": self._score(row["cls"], row["subject"]),
                })
        for l in self.lessons:
            self.by_class[l["cls"]].append(l)

        # сколько уроков ставить в каждый день: базово поровну, остаток —
        # в дни, которым МР отводит большую долю трудности
        for cls, items in self.by_class.items():
            days = self._days_of(cls)
            total = len(items)
            limits = sanpin.DAY_SHARE.get(len(days), sanpin.DAY_SHARE[6])[1]
            priority = sorted(days, key=lambda d: -sum(limits.get(d, (0, 0))) / 2)
            cap = sanpin.max_day(_grade(cls))
            base, extra = divmod(total, len(days))
            lens = {d: base for d in days}
            i = 0
            while extra > 0:
                d = priority[i % len(priority)]
                if lens[d] < cap["relief"]:
                    lens[d] += 1
                    extra -= 1
                i += 1
                if i > 200:
                    break
            # больше нормы допускается только один день в неделю
            over = [d for d in days if lens[d] > cap["norm"]]
            while len(over) > 1:
                d = over.pop()
                room = [x for x in days if lens[x] < cap["norm"]]
                if not room:
                    break
                lens[d] -= 1
                lens[min(room, key=lambda x: lens[x])] += 1
            for d in days:
                self.day_len[(cls, d)] = lens[d]

    def slots_of(self, cls: str) -> list[tuple[str, int]]:
        out = []
        for d in self._days_of(cls):
            for n in range(1, self.day_len[(cls, d)] + 1):
                out.append((d, n))
        return out

    # ---------- начальная расстановка ----------
    def seed(self) -> None:
        """Жадно раскладывает уроки, начиная с самых «неудобных»."""
        busy_teacher: set[tuple] = set()
        free = {cls: self.slots_of(cls) for cls in self.by_class}
        for slots in free.values():
            self.rnd.shuffle(slots)

        load = Counter(l["teacher"] for l in self.lessons if l["teacher"])
        order = sorted(self.lessons,
                       key=lambda l: (-load.get(l["teacher"], 0), -l["score"],
                                      l["cls"], l["subject"]))
        for l in order:
            cls = l["cls"]
            shift = self.classes[cls]["shift"]
            best, best_cost = None, None
            for idx, (d, n) in enumerate(free[cls]):
                if l["teacher"] and (l["teacher"], d, shift, n) in busy_teacher:
                    continue
                cost = self._seed_cost(l, d, n)
                if best_cost is None or cost < best_cost:
                    best, best_cost = idx, cost
                    if cost == 0:
                        break
            if best is None:            # свободного слота без накладки нет
                best = 0
            d, n = free[cls].pop(best)
            l["day"], l["n"] = d, n
            if l["teacher"]:
                busy_teacher.add((l["teacher"], d, shift, n))

    def _seed_cost(self, lesson: dict, day: str, n: int) -> int:
        """Грубая оценка места при первичной расстановке."""
        cls = lesson["cls"]
        same_day = [x for x in self.by_class[cls] if x["day"] == day]
        cost = 0
        for x in same_day:
            if x["subject"] == lesson["subject"]:
                cost += 120                      # предмет уже стоит в этот день
                if abs(x["n"] - n) == 1 and _grade(cls) <= 4:
                    cost += 800                  # сдвоенный в начальной школе
        if not rules.is_extracurricular(lesson["subject"]):
            cap = sanpin.max_day(_grade(cls))
            academic = sum(1 for x in same_day
                           if not rules.is_extracurricular(x["subject"]))
            if academic >= cap["norm"]:
                cost += 300
        last = self.day_len[(cls, day)]
        if lesson["score"] >= 9 and n in (1, last):
            cost += 50
        if lesson["score"] <= 3 and 1 < n < last:
            cost += 15
        return cost

    # ---------- штрафы ----------
    def cost_class_day(self, cls: str, day: str) -> int:
        items = [l for l in self.by_class[cls] if l["day"] == day]
        if not items:
            return 0
        items.sort(key=lambda l: l["n"])
        cost = 0
        counts = Counter(l["subject"] for l in items)
        for subj, k in counts.items():
            if k == 2:
                cost += W_SUBJECT_TWICE
            elif k >= 3:
                cost += W_SUBJECT_THRICE * (k - 2)
        if _grade(cls) <= 4:
            for a, b in zip(items, items[1:]):
                if a["subject"] == b["subject"] and b["n"] == a["n"] + 1 \
                        and "физическ" not in a["subject"].lower():
                    cost += W_DOUBLE_PRIMARY
        scored = [l for l in items if l["score"]]
        if len(scored) >= 3:
            top = max(l["score"] for l in scored)
            middle = [l["score"] for l in scored if items[0]["n"] < l["n"] < items[-1]["n"]]
            if top > (max(middle) if middle else 0):
                for l in scored:
                    if l["score"] == top and l["n"] in (items[0]["n"], items[-1]["n"]):
                        cost += W_HARD_EDGE
        return cost

    def cost_class_week(self, cls: str) -> int:
        """Отклонение дневных сумм баллов от диапазонов МР 2.4.0331-23
        плюс превышение дневного лимита уроков (внеурочные в него не входят)."""
        days = self._days_of(cls)
        cap = sanpin.max_day(_grade(cls))
        academic = {d: sum(1 for l in self.by_class[cls]
                           if l["day"] == d and not rules.is_extracurricular(l["subject"]))
                    for d in days}
        over = 0
        relief_days = 0
        for d in days:
            k = academic[d]
            if k > cap["relief"]:
                over += k - cap["relief"]
            if cap["norm"] < k <= cap["relief"]:
                relief_days += 1
        limit_cost = over * W_DAY_OVER + max(0, relief_days - 1) * W_DAY_OVER
        totals = {d: sum(l["score"] for l in self.by_class[cls] if l["day"] == d) for d in days}
        week = sum(totals.values())
        if not week:
            return 0
        limits = sanpin.DAY_SHARE.get(len(days), sanpin.DAY_SHARE[6])
        cost = 0
        for d in days:
            share = totals[d] / week * 100
            miss = min(
                max(lo - share, share - hi, 0)
                for var in limits.values()
                for lo, hi in [var.get(d, (0, 100))]
            )
            cost += int(miss * W_DAY_SHARE)
        return cost + limit_cost

    def cost_teacher(self, tid: str) -> int:
        mine = [l for l in self.lessons if l["teacher"] == tid and l["day"]]
        if not mine:
            return 0
        cost = 0
        seen = defaultdict(list)
        for l in mine:
            shift = self.classes[l["cls"]]["shift"]
            seen[(l["day"], shift)].append(l["n"])
        for (day, _shift), nums in seen.items():
            dup = len(nums) - len(set(nums))
            cost += dup * W_TEACHER_CLASH
            span = sorted(set(nums))
            cost += (span[-1] - span[0] + 1 - len(span)) * W_TEACHER_WINDOW
        per_day = defaultdict(int)
        for l in mine:
            per_day[l["day"]] += 1
        for day, k in per_day.items():
            if k == 1:
                cost += W_TEACHER_ONE
        cost += self._cost_prefs(tid, mine, per_day)
        return cost

    def _cost_prefs(self, tid: str, mine: list[dict], per_day: dict) -> int:
        cost = 0
        for p in self.prefs:
            if p.get("teacher") != tid:
                continue
            w = W_PREF_HARD if p.get("hard") else W_PREF_SOFT
            kind = p.get("kind")
            if kind == "no_day":
                cost += w * per_day.get(p.get("day"), 0)
            elif kind == "no_slot":
                cost += w * sum(1 for l in mine
                                if l["day"] == p.get("day") and l["n"] == p.get("n"))
            elif kind == "max_per_day":
                limit = int(p.get("value", 7))
                cost += w * sum(max(0, k - limit) for k in per_day.values())
            elif kind == "free_day":
                cost += w * (0 if any(per_day.get(d, 0) == 0
                                      for d in self._days_of(mine[0]["cls"])) else 1)
            elif kind == "early":
                cost += int(w / 20) * sum(max(0, l["n"] - int(p.get("value", 4))) for l in mine)
        return cost

    def cost_rooms(self) -> int:
        busy = Counter()
        for l in self.lessons:
            if l.get("room") and l["day"]:
                busy[(l["room"], l["day"], self.classes[l["cls"]]["shift"], l["n"], l["cls"])] += 0
                busy[(l["room"], l["day"], self.classes[l["cls"]]["shift"], l["n"])] += 1
        return sum((k - 1) * W_ROOM_CLASH for k in busy.values() if k > 1)

    def total_cost(self) -> int:
        cost = 0
        for cls in self.by_class:
            cost += self.cost_class_week(cls)
            for d in self._days_of(cls):
                cost += self.cost_class_day(cls, d)
        for tid in {l["teacher"] for l in self.lessons if l["teacher"]}:
            cost += self.cost_teacher(tid)
        return cost

    def _local_cost(self, cls: str, days: set, tids: set) -> int:
        cost = self.cost_class_week(cls)
        for d in days:
            cost += self.cost_class_day(cls, d)
        for tid in tids:
            cost += self.cost_teacher(tid)
        return cost

    # ---------- локальный поиск ----------
    def improve(self, seconds: float = 20.0, on_progress=None) -> dict:
        start = time.time()
        cost = self.total_cost()
        best = cost
        steps = accepted = 0
        classes = [c for c in self.by_class if len(self.by_class[c]) > 1]
        t0, t1 = 900.0, 1.0

        while True:
            elapsed = time.time() - start
            if elapsed >= seconds:
                break
            temp = t0 * (t1 / t0) ** (elapsed / seconds)
            for _ in range(400):
                steps += 1
                cls = self.rnd.choice(classes)
                items = self.by_class[cls]
                a, b = self.rnd.sample(items, 2)
                if a["day"] == b["day"] and a["n"] == b["n"]:
                    continue
                if id(a) in self.pinned or id(b) in self.pinned:
                    continue
                days = {a["day"], b["day"]}
                tids = {t for t in (a["teacher"], b["teacher"]) if t}
                before = self._local_cost(cls, days, tids)
                a["day"], b["day"] = b["day"], a["day"]
                a["n"], b["n"] = b["n"], a["n"]
                after = self._local_cost(cls, days, tids)
                delta = after - before
                if delta <= 0 or self.rnd.random() < math.exp(-delta / max(temp, 1e-6)):
                    cost += delta
                    accepted += 1
                    if cost < best:
                        best = cost
                else:
                    a["day"], b["day"] = b["day"], a["day"]
                    a["n"], b["n"] = b["n"], a["n"]
            if on_progress:
                on_progress(elapsed / seconds, cost)

        return {"cost": cost, "steps": steps, "accepted": accepted,
                "seconds": round(time.time() - start, 1)}

    # ---------- результат ----------
    def to_lessons(self) -> list[dict]:
        out = []
        for i, l in enumerate(sorted(self.lessons,
                                     key=lambda x: (x["cls"], sanpin.DAYS.index(x["day"]), x["n"])), 1):
            out.append({"id": i, "cls": l["cls"], "day": l["day"], "n": l["n"],
                        "subject": l["subject"], "room": l["room"],
                        "teacher": l["teacher"], "score_file": None})
        return out

    def report(self) -> dict:
        clashes = windows = 0
        for tid in {l["teacher"] for l in self.lessons if l["teacher"]}:
            mine = defaultdict(list)
            for l in self.lessons:
                if l["teacher"] == tid:
                    mine[(l["day"], self.classes[l["cls"]]["shift"])].append(l["n"])
            for nums in mine.values():
                clashes += len(nums) - len(set(nums))
                s = sorted(set(nums))
                windows += s[-1] - s[0] + 1 - len(s)
        prefs_total = len(self.prefs)
        prefs_ok = 0
        for p in self.prefs:
            mine = [l for l in self.lessons if l["teacher"] == p.get("teacher")]
            per_day = Counter(l["day"] for l in mine)
            if self._cost_prefs(p["teacher"], mine, per_day) == 0:
                prefs_ok += 1
        return {"lessons": len(self.lessons), "clashes": clashes, "windows": windows,
                "prefs_total": prefs_total, "prefs_ok": prefs_ok,
                "cost": self.total_cost()}


def build(model: dict, scores: dict | None = None, prefs: list | None = None,
          options: dict | None = None) -> tuple[list[dict], dict]:
    """Собирает расписание. Возвращает список уроков и отчёт."""
    opt = options or {}
    attempts = int(opt.get("attempts", 1))
    seconds = float(opt.get("seconds", 20))
    best = None
    for k in range(attempts):
        b = Builder(model, scores, prefs, {**opt, "seed": opt.get("seed", 1) + k * 7919})
        b.seed()
        run = b.improve(seconds / attempts)
        rep = {**b.report(), **run, "attempt": k + 1}
        if best is None or rep["cost"] < best[1]["cost"]:
            best = (b.to_lessons(), rep)
    return best
