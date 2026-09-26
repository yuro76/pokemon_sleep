#!/usr/bin/env python3
"""フィールドごとの出現ポケモンを取得して data/fields.json を再生成する。

データ元 (上から順に試す):
  1. Serebii のリサーチエリアページ https://www.serebii.net/pokemonsleep/locations/
  2. YoheiOhto/sleepbox-compass の data/seed_encounters.json (MIT License。Serebii から生成されたもの。
     ワカクサ本島は含まれない)

取得できなかったフィールドは、既存の data/fields.json の内容をそのまま残す。
新フィールド・新ポケモンの追加があったら実行する:

    python3 .claude/skills/pokesleep-iv/scripts/update_fields.py
"""
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT = DATA_DIR / "fields.json"
SEREBII = "https://www.serebii.net/pokemonsleep/locations/{slug}.shtml"
SEED = "https://raw.githubusercontent.com/YoheiOhto/sleepbox-compass/main/data/seed_encounters.json"

# index は pokesleep-tool のフィールド番号 (イベントの fixedAreas と対応)
FIELDS = [
    {"index": 0, "name": "ワカクサ本島", "name_en": "Greengrass Isle", "slug": "greengrassisle",
     "expert": False, "berry_types": []},
    {"index": 1, "name": "シアンの砂浜", "name_en": "Cyan Beach", "slug": "cyanbeach",
     "expert": False, "berry_types": ["water", "fairy", "flying"]},
    {"index": 2, "name": "トープ洞窟", "name_en": "Taupe Hollow", "slug": "taupehollow",
     "expert": False, "berry_types": ["ground", "fire", "rock"]},
    {"index": 3, "name": "ウノハナ雪原", "name_en": "Snowdrop Tundra", "slug": "snowdroptundra",
     "expert": False, "berry_types": ["ice", "normal", "dark"]},
    {"index": 4, "name": "ラピスラズリ湖畔", "name_en": "Lapis Lakeside", "slug": "lapislakeside",
     "expert": False, "berry_types": ["grass", "psychic", "fighting"]},
    {"index": 5, "name": "ゴールド旧発電所", "name_en": "Old Gold Power Plant", "slug": "oldgoldpowerplant",
     "expert": False, "berry_types": ["electric", "ghost", "steel"]},
    {"index": 6, "name": "アンバー渓谷", "name_en": "Amber Canyon", "slug": "ambercanyon",
     "expert": False, "berry_types": ["poison", "bug", "dragon"]},
    # EX は元のフィールドと同じ出現ポケモンとみなす
    {"index": 7, "name": "ワカクサ本島 EX", "name_en": "Greengrass Isle (Expert)", "slug": None,
     "expert": True, "berry_types": [], "same_as": 0},
    {"index": 8, "name": "シアンの砂浜 EX", "name_en": "Cyan Beach (Expert)", "slug": None,
     "expert": True, "berry_types": ["water", "fairy", "flying"], "same_as": 1},
]
SLEEP_TYPES = {"Dozing": "うとうと", "Snoozing": "すやすや", "Slumbering": "ぐっすり"}

# Serebii の表記 → data/pokemon.json の name_en (1つの表記が複数に対応することもある)
NAME_ALIAS = {
    "Alolan Vulpix": ["Vulpix (Alola)"],
    "Alolan Ninetales": ["Ninetales (Alola)"],
    "Paldean Wooper": ["Wooper (Paldea)"],
    "Toxtricity Amped Form": ["Toxtricity (Amped)"],
    "Toxtricity Low Key Form": ["Toxtricity (Low Key)"],
    "Pumpkaboo": ["Pumpkaboo (Small)", "Pumpkaboo (Medium)", "Pumpkaboo (Large)", "Pumpkaboo (Jumbo)"],
    "Gourgeist": ["Gourgeist (Small)", "Gourgeist (Medium)", "Gourgeist (Large)", "Gourgeist (Jumbo)"],
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_serebii(source):
    source = source.split("Sleep Style Unlock Chart", 1)[0]
    result = {}
    for en, ja in SLEEP_TYPES.items():
        start = source.find(f"<h3>{en}</h3>")
        if start < 0:
            result[ja] = []
            continue
        ends = [i for i in (source.find(f"<h3>{o}</h3>", start + 1) for o in SLEEP_TYPES) if i >= 0]
        block = source[start:min(ends) if ends else len(source)]
        names = re.findall(r'<a href="/pokemonsleep/pokemon/[^"]+\.shtml"><u>([^<]+)</u></a>', block)
        result[ja] = list(dict.fromkeys(html.unescape(n) for n in names))
    if not any(result.values()):
        raise ValueError("出現ポケモンが読み取れませんでした")
    return result


def to_names(encounters, known, unknown):
    out = {}
    for sleep_type, names in encounters.items():
        lst = []
        for n in names:
            for en in NAME_ALIAS.get(n, [n]):
                if en in known:
                    lst.append(en)
                else:
                    unknown.add(n)
        out[sleep_type] = list(dict.fromkeys(lst))
    return out


def main():
    known = {p["name_en"] for p in json.loads((DATA_DIR / "pokemon.json").read_text(encoding="utf-8"))["pokemon"]}
    old = {}
    if OUT.exists():
        old = {f["index"]: f for f in json.loads(OUT.read_text(encoding="utf-8"))["fields"]}

    seed = None
    unknown = set()
    fields = []
    for f in FIELDS:
        entry = {k: v for k, v in f.items() if k != "slug"}
        entry["encounters"], entry["source"], entry["updated"] = None, None, None
        if f["slug"]:
            url = SEREBII.format(slug=f["slug"])
            try:
                entry["encounters"] = to_names(parse_serebii(fetch(url)), known, unknown)
                entry["source"], entry["updated"] = url, date.today().isoformat()
            except Exception as e:  # noqa: BLE001  取得できなければ次のデータ元へ
                print(f"{f['name']}: Serebii から取得できませんでした ({e})", file=sys.stderr)
                if seed is None:
                    try:
                        seed = json.loads(fetch(SEED))
                    except Exception as e2:  # noqa: BLE001
                        print(f"sleepbox-compass から取得できませんでした ({e2})", file=sys.stderr)
                        seed = {}
                if f["name"] in seed.get("fields", {}):
                    entry["encounters"] = to_names(seed["fields"][f["name"]], known, unknown)
                    entry["source"] = f"{SEED} (出典: {seed.get('source')})"
                    entry["updated"] = seed.get("updated")
            if entry["encounters"] is None and old.get(f["index"], {}).get("encounters"):
                prev = old[f["index"]]
                entry["encounters"], entry["source"], entry["updated"] = (
                    prev["encounters"], prev.get("source"), prev.get("updated"))
                print(f"{f['name']}: 既存のデータを残しました", file=sys.stderr)
            if entry["encounters"] is None:
                print(f"{f['name']}: 出現ポケモンのデータがありません", file=sys.stderr)
        fields.append(entry)

    if unknown:
        print(f"pokemon.json にない名前 (NAME_ALIAS に追加してください): {', '.join(sorted(unknown))}",
              file=sys.stderr)
    data = {
        "note": "encounters はフィールドに出現するポケモン (name_en) を睡眠タイプ別に並べたもの。"
                "null はデータなし。same_as は元のフィールドと同じ出現とみなすことを表す。"
                "手で追加・修正してもよい。",
        "fields": fields,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(1 for f in fields if f["encounters"])
    print(f"wrote {n} fields with encounters -> {OUT}")


if __name__ == "__main__":
    main()
