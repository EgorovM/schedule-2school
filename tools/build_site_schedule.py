# -*- coding: utf-8 -*-
"""Переносит расписание из рабочей модели завуча в публичный сайт.

    python3 tools/build_site_schedule.py

Читает data/schedule.json (её правит инструмент раписания) и подставляет
компактные данные в блок <script id="sched-data"> файла index.html.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from raspisanie import sanpin  # noqa: E402

GROUPS = [
    ("1—4 классы", "1 смена", lambda c: c["grade"] <= 4),
    ("5, 9—11 классы", "1 смена", lambda c: c["grade"] > 4 and c["shift"] == 1),
    ("6—8 классы", "2 смена", lambda c: c["grade"] > 4 and c["shift"] == 2),
]


def cls_key(name):
    m = re.match(r"(\d+)\s*(\D*)", name)
    return (int(m.group(1)), m.group(2)) if m else (99, name)


def main() -> int:
    model = json.loads((ROOT / "data" / "schedule.json").read_text(encoding="utf-8"))
    classes = {c["id"]: c for c in model["classes"]}
    bells = {s: {int(k): v for k, v in b.items()} for s, b in model["bells"].items()}

    shifts = []
    for note, shift_name, pick in GROUPS:
        ids = sorted([c["id"] for c in model["classes"] if pick(c)], key=cls_key)
        if not ids:
            continue
        rooms = {i: classes[i]["room"] for i in ids if classes[i].get("room")}
        shift_no = str(classes[ids[0]]["shift"])
        by_day = {}
        for l in model["lessons"]:
            if l["cls"] not in ids:
                continue
            day = by_day.setdefault(l["day"], {})
            slot = day.setdefault(l["n"], {})
            label = l["subject"] + ("|" + l["room"] if l.get("room") else "")
            slot[l["cls"]] = label
        days = []
        for d in sanpin.DAYS:
            if d not in by_day:
                continue
            lessons = [{"n": n, "t": bells.get(shift_no, {}).get(n, "").replace("—", "-"),
                        "b": by_day[d][n]}
                       for n in sorted(by_day[d])]
            days.append({"d": sanpin.DAY_FULL[d], "l": lessons})
        shifts.append({"name": shift_name, "note": note, "classes": ids,
                       "rooms": rooms, "days": days})

    blob = json.dumps({"year": model["meta"].get("year", ""), "shifts": shifts},
                      ensure_ascii=False, separators=(",", ":"))

    idx = ROOT / "index.html"
    html = idx.read_text(encoding="utf-8")
    new = re.sub(r'(<script id="sched-data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + blob.replace("\\", "\\\\") + m.group(2),
                 html, flags=re.S)
    if new == html:
        print("маркер <script id=\"sched-data\"> не найден — сайт не обновлён")
        return 1
    idx.write_text(new, encoding="utf-8")
    print(f"index.html обновлён: {sum(len(s['classes']) for s in shifts)} классов, "
          f"{len(blob) / 1024:.1f} КБ данных")
    for s in shifts:
        print(f"  {s['note']:16} {s['name']}  {', '.join(s['classes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
