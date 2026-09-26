#!/usr/bin/env python3
"""次の週(月曜4:00〜翌月曜4:00)にどのフィールドへ行くのが良いかをランキングする。

  python3 .claude/skills/pokesleep-iv/scripts/field_rank.py [--week YYYY-MM-DD] [--events 追加イベント.json]
                                                           [--exclude フィールド ...] [--sleep-type うとうと ...]

優先順位:
  1. イベントでメリットがあるフィールド (イベント対象フィールド・好きなきのみの固定・対象タイプが好きなきのみ)
     や、新規登場ポケモン(厳選完了していないもの)が出るフィールド
  2. イベントで差がつかなければ、食材タイプで厳選完了していないポケモンが多く出るフィールド
     (記録なし=1点、キープのみ=0.2点。そのフィールドでしか出ないポケモンは 記録なし+0.5点・キープ+0.1点)
     出現ポケモンは進化していない姿 (ゼニガメ等) だけを数える (進化した姿で出会っても厳選の手間は同じではないため)

データ:
  data/events.json  … イベント (update_data.py で更新)
  data/pokemon.json … arrival(実装日) から新規登場ポケモンを判定 (update_data.py で更新)
  data/fields.json  … フィールドごとの出現ポケモン (update_fields.py で更新)
  records/pokemon.json … 厳選状況 (pokesleep.py save で記録したもの)。記録はセッション(ブランチ)ごとに
                         更新されていくので、git fetch して全ブランチのうち最後に更新された記録を使う

--events には、data/events.json にまだ入っていないイベント(公式のお知らせで見つけたもの)を渡す:
  [{"name": "ハロウィン2026", "start": "2026-10-19T04:00", "end": "2026-10-26T04:00",
    "fields": ["ワカクサ本島"], "pokemon": ["ゴース"], "types": ["ghost"], "memo": "ゴーストタイプの食材+1"}]
  fields  … メリットがあるフィールド (空なら全フィールド共通のイベントとして扱う)
  pokemon … 新登場・期間限定などで狙いたいポケモン (出現フィールドは fields.json から探す)
  types   … 出やすくなる・ボーナスがあるタイプ (好きなきのみに含むフィールドを優先)
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import records_sync  # noqa: E402
from pokesleep import (DATA, POKEMON_BY_EN, POKEMON_BY_JA, RECORDS, REPO_ROOT, SKILL_DIR,  # noqa: E402
                       load_records, normalize)

JST = ZoneInfo("Asia/Tokyo")
FIELDS = json.loads((SKILL_DIR / "data" / "fields.json").read_text(encoding="utf-8"))["fields"]
EVENTS = json.loads((SKILL_DIR / "data" / "events.json").read_text(encoding="utf-8"))

SIZE_FORMS = {"Small", "Medium", "Large", "Jumbo"}  # バケッチャ・パンプジンのサイズ違いは1種類として扱う
TYPE_JA = {
    "normal": "ノーマル", "fire": "ほのお", "water": "みず", "electric": "でんき", "grass": "くさ",
    "ice": "こおり", "fighting": "かくとう", "poison": "どく", "ground": "じめん", "flying": "ひこう",
    "psychic": "エスパー", "bug": "むし", "rock": "いわ", "ghost": "ゴースト", "dragon": "ドラゴン",
    "dark": "あく", "steel": "はがね", "fairy": "フェアリー",
}
TYPE_JA2EN = {v: k for k, v in TYPE_JA.items()}
BERRY_OF_TYPE = {p["type"]: p["berry"] for p in DATA["pokemon"]}
SPECIALTY_JA = {"Berries": "きのみ", "Ingredients": "食材", "Skills": "スキル", "All": "オール"}
EFFECT_JA = {
    "berry": "きのみ+{}個", "ingredient": "食材+{}個", "skillTrigger": "スキル発生率×{}",
    "skillLevel": "メインスキルLv+{}", "dish": "料理エナジー×{}", "carryLimitAdd": "最大所持数+{}",
    "carryLimitMul": "最大所持数×{}", "globalCarryLimitAdd": "全員の最大所持数+{}",
    "berryBurst": "ベリーバースト×{}",
}
EFFECT_DEFAULT = {"berry": 0, "ingredient": 0, "skillTrigger": 1, "skillLevel": 0, "dish": 1,
                  "carryLimitAdd": 0, "carryLimitMul": 1, "globalCarryLimitAdd": 0, "berryBurst": 1}

W_EVENT_FIELD = 3     # イベント対象フィールド
W_NEW_POKEMON = 2     # 新規登場ポケモン (厳選完了していない) 1種ごと
W_TYPE_MATCH = 1      # イベント対象タイプが好きなきのみに入っている (1タイプごと)
W_UNRECORDED = 1.0    # 食材タイプで記録なし
W_KEEP = 0.2          # 食材タイプでキープのみ (候補はいるので、記録なしを優先する)
W_EXCLUSIVE = 0.5     # そのフィールドでしか出ない (記録なし)
W_EXCLUSIVE_KEEP = 0.1  # そのフィールドでしか出ない (キープのみ)


def fail(msg):
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


def find_pokemon(name):
    if name in POKEMON_BY_EN:
        return POKEMON_BY_EN[name]
    if name in POKEMON_BY_JA:
        return POKEMON_BY_JA[name]
    norm = {normalize(k): v for k, v in POKEMON_BY_JA.items()}
    return norm.get(normalize(name))


def find_field(name):
    for f in FIELDS:
        if name in (f["name"], f["name_en"], str(f["index"])) or normalize(name) == normalize(f["name"]):
            return f
    fail(f"フィールド「{name}」が見つかりません。候補: {', '.join(f['name'] for f in FIELDS)}")


def parse_time(s):
    return datetime.fromisoformat(s).replace(tzinfo=JST) if s else None


# ---------------------------------------------------------------- 厳選状況

def group_key(p):
    """厳選の単位 = 最終進化 (サイズ違いはまとめる)"""
    if p.get("form") in SIZE_FORMS:
        return f"{p['ancestor']}:size"
    return p["name_en"]


def finals_of(p):
    """p から進化しうる最終進化の一覧"""
    if p["evolutionLeft"] == 0:
        return [p]
    form = p.get("form")
    finals = [q for q in DATA["pokemon"] if q["ancestor"] == p["ancestor"] and q["evolutionLeft"] == 0
              and (q.get("form") == form or (form in SIZE_FORMS and q.get("form") in SIZE_FORMS))]
    return finals or [p]


def group_label(p):
    name = p["name_ja"]
    if p.get("form") in SIZE_FORMS:
        name = name.split(" (")[0]
    return name


def latest_records(fetch=True):
    """記録はセッション(ブランチ)ごとに更新されていくので、全ブランチのうち最後に更新された
    records/pokemon.json を作業ツリーに取り込んでから読む (records_sync.py)。戻り値: (記録, 出どころ)"""
    src = records_sync.sync(fetch=fetch)[RECORDS.relative_to(REPO_ROOT).as_posix()]
    return load_records(), src


def selection_status(records):
    """厳選の単位ごとの状態 (厳選完了 > キープ)"""
    rank = {"厳選完了": 2, "キープ": 1}
    status = {}
    for r in records:
        p = POKEMON_BY_EN.get(r["name_en"])
        if p is None:
            continue
        finals = finals_of(p)
        keys = {group_key(q) for q in finals}
        if len(keys) != 1:  # 進化先が決まっていない (イーブイ等) 記録は数えない
            continue
        k = keys.pop()
        if rank.get(r["status"], 0) > rank.get(status.get(k), 0):
            status[k] = r["status"]
    return status


# ---------------------------------------------------------------- フィールド

def encounters(f):
    if f.get("same_as") is not None:
        return FIELDS[f["same_as"]]["encounters"]
    return f["encounters"]


def field_groups(f, sleep_types):
    """フィールドに出るポケモンを厳選の単位にまとめる。{key: {"final": p, "spawn": {種族名...}, "sleep": {...}}}"""
    enc = encounters(f)
    if not enc:
        return None
    groups = {}
    for st, names in enc.items():
        if sleep_types and st not in sleep_types:
            continue
        for n in names:
            p = POKEMON_BY_EN.get(n)
            if p is None or p["evolutionCount"] > 0:  # 進化していない姿だけを出現対象にする
                continue
            for q in finals_of(p):
                g = groups.setdefault(group_key(q), {"final": q, "spawn": set(), "sleep": set()})
                g["spawn"].add(group_label(p))
                g["sleep"].add(st)
    return groups


# ---------------------------------------------------------------- イベント

def effects_text(effects):
    out = []
    for k, v in effects.items():
        if k in EFFECT_JA and v != EFFECT_DEFAULT.get(k):
            out.append(EFFECT_JA[k].format(v))
    if effects.get("bigBerry"):
        out.append("大きなきのみ")
    return "、".join(out)


def target_text(target):
    parts = []
    if target.get("type"):
        parts.append("・".join(TYPE_JA.get(t, t) for t in target["type"]) + "タイプ")
    if target.get("specialty"):
        parts.append(f"とくい{SPECIALTY_JA.get(target['specialty'], target['specialty'])}")
    return "・".join(parts) or "全ポケモン"


def collect_events(start, end, extra):
    """週と重なるイベントを共通の形にそろえる"""
    events = []
    for e in EVENTS["bonus"]:
        s, t = parse_time(e["start"]), parse_time(e["end"])
        if s < end and t > start:
            eff = e.get("effects", {})
            fixed = [b for b in eff.get("fixedBerries", []) if b]
            events.append({
                "name": e.get("name_ja", e["name"]), "start": s, "end": t,
                "fields": list(eff.get("fixedAreas", [])),
                "fixed_berries": fixed,
                "types": list(e.get("target", {}).get("type", [])),
                "pokemon": [],
                "memo": f"{target_text(e.get('target', {}))}: {effects_text(eff) or '効果なし'}",
                "source": "data/events.json",
            })
    for e in extra:
        s, t = parse_time(e.get("start")), parse_time(e.get("end"))
        if (s and s >= end) or (t and t <= start):
            continue
        types = [TYPE_JA2EN.get(x, x) for x in e.get("types", [])]
        pokemon = []
        for n in e.get("pokemon", []):
            p = find_pokemon(n)
            if p is None:
                print(f"警告: イベント「{e.get('name')}」のポケモン「{n}」が見つかりません", file=sys.stderr)
            else:
                pokemon.append(p)
        events.append({
            "name": e.get("name", "(名前なし)"), "start": s, "end": t,
            "fields": [find_field(x)["index"] for x in e.get("fields", [])],
            "fixed_berries": [], "types": types, "pokemon": pokemon,
            "memo": e.get("memo", ""), "source": "--events",
        })
    return events


def drowsy_days(start, end):
    days = []
    for e in EVENTS["drowsy"]:
        d = datetime.fromisoformat(e["day"]).replace(hour=4, tzinfo=JST)
        if start <= d < end:
            days.append((d, e["bonus"]))
    return days


# ---------------------------------------------------------------- メイン

def fmt_day(d):
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]})"


def fmt_period(s, t):
    def one(d):
        return f"{fmt_day(d)} {d.strftime('%H:%M')}" if d else "?"
    return f"{one(s)}〜{one(t)}"


def next_week_start(now):
    """次の月曜 4:00 (JST)。今が月曜 4:00 前なら今日の 4:00"""
    base = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if now.weekday() == 0 and now < base:
        return base
    return base + timedelta(days=(7 - now.weekday()) % 7 or 7)


def main():
    ap = argparse.ArgumentParser(description="次の週に行くフィールドのランキング")
    ap.add_argument("--week", help="週の開始日 YYYY-MM-DD (その日の4:00から7日間)。省略時は次の月曜")
    ap.add_argument("--events", help="data/events.json にない追加イベントの JSON ファイル")
    ap.add_argument("--exclude", nargs="*", default=[], help="除外するフィールド (未開放など)")
    ap.add_argument("--sleep-type", nargs="*", default=[], choices=["うとうと", "すやすや", "ぐっすり"],
                    help="この睡眠タイプで出るポケモンだけで数える")
    ap.add_argument("--new-days", type=int, default=14,
                    help="週の開始の何日前以降に実装されたポケモンを新規登場とみなすか (既定14)")
    ap.add_argument("--top", type=int, default=3, help="詳細を表示するフィールド数")
    ap.add_argument("--no-fetch", action="store_true", help="git fetch せずに手元のブランチだけで記録を探す")
    args = ap.parse_args()

    now = datetime.now(JST)
    if args.week:
        start = datetime.fromisoformat(args.week).replace(hour=4, minute=0, tzinfo=JST)
    else:
        start = next_week_start(now)
    end = start + timedelta(days=7)
    extra = []
    if args.events:
        extra = json.loads(Path(args.events).read_text(encoding="utf-8"))
        if isinstance(extra, dict):
            extra = [extra]

    excluded = {find_field(x)["index"] for x in args.exclude}
    fields = [f for f in FIELDS if f["index"] not in excluded]
    records, records_src = latest_records(fetch=not args.no_fetch)
    status = selection_status(records)
    groups = {f["index"]: field_groups(f, args.sleep_type) for f in fields}

    # 通常フィールド(EX 以外)で何か所に出るか
    appear = {}
    for f in fields:
        if not f["expert"] and groups[f["index"]]:
            for k in groups[f["index"]]:
                appear[k] = appear.get(k, 0) + 1

    events = collect_events(start, end, extra)
    gsd = drowsy_days(start, end)

    # 新規登場ポケモン
    new_from = start - timedelta(days=args.new_days)
    new_pokemon = {}
    for p in DATA["pokemon"]:
        if p.get("arrival") and new_from <= datetime.fromisoformat(p["arrival"]).replace(hour=4, tzinfo=JST) < end:
            new_pokemon[p["name_en"]] = (p, f"{p['arrival']} 実装")
    for e in events:
        for p in e["pokemon"]:
            new_pokemon.setdefault(p["name_en"], (p, e["name"]))

    rows = []
    for f in fields:
        idx, g = f["index"], groups[f["index"]]
        merits, ev_score = [], 0.0
        for e in events:
            if idx in e["fields"]:
                ev_score += W_EVENT_FIELD
                berries = "・".join(BERRY_OF_TYPE[b] for b in e["fixed_berries"])
                merits.append(f"{e['name']}の対象フィールド" + (f"(好きなきのみに{berries}が固定)" if berries else ""))
            elif not e["fields"] and e["types"] and not f["expert"] and f["berry_types"]:
                hit = [t for t in e["types"] if t in f["berry_types"]]
                if hit:
                    ev_score += W_TYPE_MATCH * len(hit)
                    merits.append(f"{e['name']}の対象({'・'.join(TYPE_JA[t] for t in hit)})が好きなきのみ")
        new_here = []
        spawn_names = set()
        for st, names in (encounters(f) or {}).items():
            if not args.sleep_type or st in args.sleep_type:
                spawn_names.update(names)
        for en, (p, why) in new_pokemon.items():
            if en in spawn_names and status.get(group_key(finals_of(p)[0])) != "厳選完了":
                new_here.append(f"{p['name_ja']}({why})")
        for e in events:  # 出現データにないが、追加イベントで出現フィールドが指定されているポケモン
            if idx in e["fields"]:
                for p in e["pokemon"]:
                    if p["name_en"] not in spawn_names and status.get(group_key(finals_of(p)[0])) != "厳選完了":
                        new_here.append(f"{p['name_ja']}({e['name']})")
        ev_score += W_NEW_POKEMON * len(new_here)
        if new_here:
            merits.append("新規登場: " + "、".join(new_here))

        todo, sel_score = [], None
        if g:
            sel_score = 0.0
            for k, gg in g.items():
                q = gg["final"]
                if q["specialty"] != "Ingredients" or status.get(k) == "厳選完了":
                    continue
                st = status.get(k, "記録なし")
                w = W_KEEP if st == "キープ" else W_UNRECORDED
                excl = appear.get(k, 0) == 1 and not f["expert"]
                if excl:
                    w += W_EXCLUSIVE_KEEP if st == "キープ" else W_EXCLUSIVE
                sel_score += w
                todo.append({"name": group_label(q), "status": st, "exclusive": excl,
                             "spawn": sorted(gg["spawn"]), "sleep": sorted(gg["sleep"]),
                             "ings": "・".join(dict.fromkeys(
                                 DATA["ingredients"][o["name"]]["ja"] for slot in q["ingredients"] for o in slot))})
            todo.sort(key=lambda t: (t["status"] != "記録なし", not t["exclusive"], t["name"]))
        rows.append({"field": f, "ev_score": ev_score, "merits": merits, "sel_score": sel_score, "todo": todo})

    # EX は元のフィールドと同じ出現なので、イベントのメリットがある時だけ並べる
    rows = [r for r in rows if not r["field"]["expert"] or r["ev_score"] > 0]
    has_event = any(r["ev_score"] > 0 for r in rows)
    rows.sort(key=lambda r: (-r["ev_score"], -(r["sel_score"] if r["sel_score"] is not None else -1),
                             r["field"]["index"]))

    # ---- 出力
    print("# 次の週のフィールドランキング")
    print(f"対象期間: {fmt_period(start, end)}")
    n_done = sum(1 for v in status.values() if v == "厳選完了")
    n_keep = sum(1 for v in status.values() if v == "キープ")
    print(f"厳選状況: 記録 {len(records)}件 → 厳選完了 {n_done}種 / キープのみ {n_keep}種")
    print(f"記録の出どころ: {records_src}")
    if records:
        print("記録済み: " + "、".join(f"{r['name']}({r['status']})" for r in records))
    if args.sleep_type:
        print(f"睡眠タイプ: {'・'.join(args.sleep_type)} のみで集計")
    print()

    print("## イベント")
    if not events and not gsd:
        print("- data/events.json・追加イベントともに、この週のイベントはありません")
    for e in events:
        where = "・".join(FIELDS[i]["name"] for i in e["fields"]) if e["fields"] else "全フィールド共通"
        print(f"- **{e['name']}** {fmt_period(e['start'], e['end'])} [{where}] {e['memo']}")
    for d, b in gsd:
        print(f"- グッドスリープデー {fmt_day(d)} ねむけパワー×{b} (全フィールド共通)")
    if new_pokemon:
        spawned = {n for f in FIELDS for names in (encounters(f) or {}).values() for n in names}
        print("- 新規登場ポケモン: " + "、".join(
            f"{p['name_ja']}({why}" + ("" if p["name_en"] in spawned else "、出現フィールドのデータなし") + ")"
            for p, why in new_pokemon.values()))
    print()

    print("## ランキング")
    print("判定: " + ("イベントでメリットがあるフィールドを優先" if has_event else
                     "イベントによる差はないので、食材タイプで厳選が終わっていないポケモンが多いフィールドを優先"))
    print()
    print("| 順位 | フィールド | イベント | 厳選スコア | 未完了の食材タイプ (記録なし/キープ) | そこでしか出ない |")
    print("|---:|---|---|---:|---|---:|")
    for i, r in enumerate(rows, 1):
        f = r["field"]
        ev = "<br>".join(r["merits"]) or "-"
        if r["sel_score"] is None:
            sel, cnt, ex = "-", "出現データなし", "-"
        else:
            un = sum(1 for t in r["todo"] if t["status"] == "記録なし")
            kp = len(r["todo"]) - un
            sel, cnt = f"{r['sel_score']:.1f}", f"{len(r['todo'])}種 ({un}/{kp})"
            ex = f"{sum(1 for t in r['todo'] if t['exclusive'])}種"
        print(f"| {i} | {f['name']} | {ev} | {sel} | {cnt} | {ex} |")
    print()

    print(f"## 上位{args.top}フィールドの狙い目 (食材タイプで厳選が終わっていないポケモン)")
    for r in rows[:args.top]:
        f = r["field"]
        print(f"### {f['name']}")
        if r["merits"]:
            print("- イベント: " + " / ".join(r["merits"]))
        if r["sel_score"] is None:
            print("- 出現ポケモンのデータがありません (data/fields.json)")
            continue
        if not r["todo"]:
            print("- 食材タイプはすべて厳選完了")
            continue
        for t in r["todo"]:
            spawn = "、".join(t["spawn"])
            name = t["name"] if spawn == t["name"] else f"{spawn} (→{t['name']})"
            print(f"- {name} [{t['status']}]" + (" ★ここでしか出ない" if t["exclusive"] else "")
                  + f" — {'・'.join(t['sleep'])}"
                  + f" / 食材: {t['ings']}")
        print()

    missing = [f["name"] for f in fields if encounters(f) is None and not f["expert"]]
    if missing:
        print(f"※ 出現ポケモンのデータがないフィールド: {'、'.join(missing)} (厳選スコアは計算していません)")
    olds = sorted({f["updated"] for f in FIELDS if f.get("updated")})
    if olds:
        print(f"※ 出現ポケモンのデータ: {olds[0]} 時点。それ以降の新ポケモンは反映されていない可能性があります")


if __name__ == "__main__":
    main()
