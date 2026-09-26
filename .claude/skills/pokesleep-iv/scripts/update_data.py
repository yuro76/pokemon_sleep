#!/usr/bin/env python3
"""ポケモン基礎データ・イベントデータを上流から取得して data/pokemon.json と data/events.json を再生成する。

データ元: https://github.com/nitoyon/pokesleep-tool (MIT License)
新ポケモン追加や数値調整のアップデートがあったら実行する:

    python3 .claude/skills/pokesleep-iv/scripts/update_data.py
"""
import json
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nitoyon/pokesleep-tool/main/src"
OUT = Path(__file__).resolve().parent.parent / "data" / "pokemon.json"
EVENTS_OUT = OUT.with_name("events.json")

# きのみ名はタイプで一意に決まる
BERRY_JA = {
    "normal": "キーのみ", "fire": "ヒメリのみ", "water": "オレンのみ",
    "electric": "ウブのみ", "grass": "ドリのみ", "ice": "チーゴのみ",
    "fighting": "クラボのみ", "poison": "カゴのみ", "ground": "フィラのみ",
    "flying": "シーヤのみ", "psychic": "マゴのみ", "bug": "ラムのみ",
    "rock": "オボンのみ", "ghost": "ブリーのみ", "dragon": "ヤチェのみ",
    "dark": "ウイのみ", "steel": "ベリブのみ", "fairy": "モモンのみ",
}

# src/util/Berry.ts
BERRY_BASE_STRENGTH = {
    "normal": 28, "fire": 27, "water": 31, "electric": 25, "grass": 30,
    "ice": 32, "fighting": 27, "poison": 32, "ground": 29, "flying": 24,
    "psychic": 26, "bug": 24, "rock": 30, "ghost": 26, "dragon": 35,
    "dark": 31, "steel": 33, "fairy": 26,
}

# src/util/PokemonRp.ts
INGREDIENT_STRENGTH = {
    "leek": 185, "mushroom": 167, "egg": 115, "potato": 124, "apple": 90,
    "herb": 130, "sausage": 103, "milk": 98, "honey": 101, "oil": 121,
    "ginger": 109, "tomato": 110, "cacao": 151, "tail": 342, "soy": 100,
    "corn": 140, "coffee": 153, "pumpkin": 250, "avocado": 162,
}

SPECIALTY_JA = {"Berries": "きのみ", "Ingredients": "食材", "Skills": "スキル", "All": "オール"}

# 上流の表記揺れ ("snozing") も吸収する
SLEEP_TYPE_JA = {"dozing": "うとうと", "snoozing": "すやすや", "snozing": "すやすや", "slumbering": "ぐっすり"}

# src/i18n/ja/common.json の area と同じ順 (フィールドの index)
AREA_JA = ["ワカクサ本島", "シアンの砂浜", "トープ洞窟", "ウノハナ雪原", "ラピスラズリ湖畔",
           "ゴールド旧発電所", "アンバー渓谷", "ワカクサ本島 EX", "シアンの砂浜 EX"]


def fetch(path):
    with urllib.request.urlopen(f"{BASE}/{path}") as r:
        return json.load(r)


def main():
    pokemons = fetch("data/pokemon.json")
    ja_poke = fetch("i18n/ja/pokemons.json")["pokemons"]
    ja_data = fetch("i18n/ja/data.json")
    ja_skills = fetch("i18n/ja/skills.json")["skills"]

    def ing_options(p):
        # スロットごとに選択可能な食材と個数
        if "mythIng" in p:
            return [
                [{"name": m["name"], "count": m[f"c{k}"]} for m in p["mythIng"] if m.get(f"c{k}", 0) > 0]
                for k in (1, 2, 3)
            ]
        slots = []
        for k in (1, 2, 3):
            opts = []
            for i in range(1, k + 1):
                ing = p.get(f"ing{i}")
                if ing is None or ing["name"].startswith("unknown") or ing.get(f"c{k}", 0) <= 0:
                    continue
                opts.append({"name": ing["name"], "count": ing[f"c{k}"]})
            slots.append(opts)
        return slots

    out = []
    for p in pokemons:
        out.append({
            "name_en": p["name"],
            "name_ja": ja_poke[p["name"]],
            "type": p["type"],
            "berry": BERRY_JA[p["type"]],
            "specialty": p["specialty"],
            "specialty_ja": SPECIALTY_JA[p["specialty"]],
            "skill": p["skill"],
            "skill_ja": ja_skills[p["skill"]]["name"],
            "frequency": p["frequency"],
            "ingRate": p["ingRate"],
            "skillRate": p["skillRate"],
            "carryLimit": p["carryLimit"],
            "fp": p.get("fp"),  # 仲良くなるのに必要なゲージ数 (5ゲージ=仲間にしやすい)
            "ancestor": p["ancestor"],
            "evolutionCount": p["evolutionCount"],
            "evolutionLeft": p["evolutionLeft"],
            "form": p.get("form"),
            "arrival": p.get("arrival"),
            "sleep_type": SLEEP_TYPE_JA.get(p.get("sleepType")),
            "mythical": "mythIng" in p,
            "ingredients": ing_options(p),
        })

    data = {
        "source": "https://github.com/nitoyon/pokesleep-tool (MIT License)",
        "updated": date.today().isoformat(),
        "berry_base_strength": BERRY_BASE_STRENGTH,
        "ingredients": {
            en: {"ja": ja_data["ingredients"][en], "strength": s}
            for en, s in INGREDIENT_STRENGTH.items()
        },
        "natures": ja_data["natures"],
        "subskills": ja_data["subskill"],
        "pokemon": out,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} pokemon -> {OUT}")

    events = fetch("data/event.json")
    ja_events = fetch("i18n/ja/events.json")["events"]

    def event_ja(name):
        ja = ja_events.get(name, name)
        # "$t(events.super skill week) vol.3" のような参照を展開
        if ja.startswith("$t(events."):
            key, rest = ja[len("$t(events."):].split(")", 1)
            ja = ja_events.get(key, key) + rest
        return ja

    ev = {
        "source": "https://github.com/nitoyon/pokesleep-tool (MIT License)",
        "updated": date.today().isoformat(),
        "areas": AREA_JA,
        "bonus": [{**e, "name_ja": event_ja(e["name"])} for e in events["bonus"]],
        "drowsy": events["drowsy"],
    }
    EVENTS_OUT.write_text(json.dumps(ev, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(ev['bonus'])} bonus events -> {EVENTS_OUT}")


if __name__ == "__main__":
    main()
