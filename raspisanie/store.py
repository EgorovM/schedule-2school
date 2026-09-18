# -*- coding: utf-8 -*-
"""Хранилище состояния: модель расписания, замены, переопределения баллов."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCHEDULE = DATA / "schedule.json"
SUBS = DATA / "substitutions.json"
SCORES = DATA / "scores.json"
BACKUPS = DATA / "backups"


def _read(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write(path: Path, payload) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def load_model() -> dict:
    return _read(SCHEDULE, {"meta": {}, "classes": [], "teachers": [],
                            "lessons": [], "bells": {}, "prior": []})


def save_model(model: dict, reason: str = "") -> None:
    """Сохраняет расписание, оставляя предыдущую версию в data/backups."""
    if SCHEDULE.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(SCHEDULE, BACKUPS / f"schedule-{stamp}.json")
        keep = sorted(BACKUPS.glob("schedule-*.json"))[:-40]
        for old in keep:
            old.unlink()
    model.setdefault("meta", {})["saved_at"] = datetime.now().isoformat(timespec="seconds")
    if reason:
        model["meta"]["last_change"] = reason
    _write(SCHEDULE, model)


def load_subs() -> dict:
    return _read(SUBS, {"absences": [], "substitutions": []})


def save_subs(data: dict) -> None:
    _write(SUBS, data)


def load_scores() -> dict:
    """Школьная таблица баллов: {предмет: {класс: балл}} — перекрывает СанПиН."""
    return _read(SCORES, {})


def save_scores(data: dict) -> None:
    _write(SCORES, data)
