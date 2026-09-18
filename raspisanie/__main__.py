# -*- coding: utf-8 -*-
"""Запуск: python3 -m raspisanie [--port 8770] [--import путь.xlsx] [--check]"""
import argparse
import sys

from . import rules, store
from .server import run


def main() -> int:
    ap = argparse.ArgumentParser(prog="raspisanie", description="Инструмент составления расписания")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--import", dest="src", help="загрузить расписание из xlsx")
    ap.add_argument("--check", action="store_true", help="только проверить и выйти")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    if a.src:
        from .importer import import_workbook
        model = import_workbook(a.src)
        store.save_model(model, f"импорт из {a.src}")
        print(f"Загружено: {len(model['classes'])} классов, {len(model['lessons'])} уроков, "
              f"{len(model['teachers'])} педработников")

    if a.check:
        r = rules.analyze(store.load_model(), store.load_scores())
        s = r["summary"]
        print(f"Уроков {s['lessons']}, нарушений {s['errors']}, предупреждений {s['warnings']}, "
              f"без учителя {s['unassigned']}")
        for i in r["issues"]:
            mark = "!" if i["level"] == "error" else "·"
            print(f" {mark} {i['text']}   [{i['source']}]")
        return 0

    run(a.port, open_browser=not a.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
