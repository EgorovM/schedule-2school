# -*- coding: utf-8 -*-
"""Собирает публичную версию сайта для GitHub Pages.

    python3 tools/build_pages.py

index.html в корне — исходник (он же публикуется как артефакт и не содержит
обвязки <html>/<head>). Здесь она добавляется, результат кладётся в docs/,
откуда GitHub Pages раздаёт сайт.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "index.html"
OUT = ROOT / "docs" / "index.html"

DESCRIPTION = ("Официальная информация МБОУ «Нюрбинская средняя общеобразовательная школа №2 "
               "им. М. С. Егорова»: расписание уроков и звонков, кружки, актированные дни, контакты.")


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    body = re.sub(r'^\s*<meta charset="utf-8">\s*\n', "", src, count=1)

    m = re.search(r"<title>(.*?)</title>", body, re.S)
    title = m.group(1).strip() if m else "Нюрбинская школа №2"

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="{DESCRIPTION}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<style>
  :root {{ color-scheme: light; padding-top: env(safe-area-inset-top, 0px);
           padding-bottom: env(safe-area-inset-bottom, 0px); }}
  body {{ margin: 0; font: 14px/1.5 system-ui, sans-serif; background: #EDF1F4; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
{body.strip()}
</body>
</html>
"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    (OUT.parent / ".nojekyll").write_text("", encoding="utf-8")
    print(f"docs/index.html собран: {len(page) / 1024:.1f} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
