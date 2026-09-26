#!/usr/bin/env python3
"""ポケモンスリープ 個体評価・記録ツール

サブコマンド:
  lookup  <名前>            ポケモンの基礎データと食材の選択肢を表示
  eval    <入力JSON>        個体を評価し、記録済み個体と比較
  save    <入力JSON>        個体を記録に追加 (--status 厳選完了|キープ)
  list    [--name 名前]     記録一覧
  update  <ID> <入力JSON>   記録の一部を上書き (レベルアップ・進化など)
  delete  <ID>              記録を削除
  require [名前 サブスキル...] 必須サブスキルの設定 (--clear で解除。引数なしで一覧)

入力JSON (ファイルパス or '-' で標準入力):
{
  "name": "ピカチュウ",           # 日本語名 (フォルムは "ピカチュウ (ハロウィン)" など)
  "level": 30,
  "nature": "いじっぱり",
  "subskills": ["おてつだいスピードM", "きのみの数S", ...],  # Lv10,25,50,70,80 の順
  "ingredients": ["とくせんリンゴ", "あったかジンジャー", "とくせんエッグ"],  # Lv1,30,60 枠 (名前 or A/B/C)
  "skill_level": 2,               # 任意
  "rp": 812,                      # 任意: スクショのRP。計算値と照合して読み取りミスを検出
  "ribbon": 0,                    # 任意: おやすみリボンの段階 (0〜4)
  "evolution_count": 1,           # 任意: 実際に進化させた回数 (最大所持数+5/回)。省略時は進化段階ぶん
  "nickname": "", "memo": ""      # 任意
}
"""
import argparse
import difflib
import functools
import json
import math
import sys
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA = json.loads((SKILL_DIR / "data" / "pokemon.json").read_text(encoding="utf-8"))
REPO_ROOT = SKILL_DIR.parent.parent.parent
RECORDS = REPO_ROOT / "records" / "pokemon.json"
REQUIRED = REPO_ROOT / "records" / "required_subskills.json"  # {"ジュカイン": ["きのみの数S"], ...}

SUBSKILL_UNLOCK = [10, 25, 50, 70, 80]
INGREDIENT_UNLOCK = [1, 30, 60]
EVAL_LEVEL = 80              # 評価・判定の基準レベル (サブスキル5つ・食材3枠すべて解放)
COMPARE_LEVELS = [60, EVAL_LEVEL]
AWAKE_HOURS = 16             # 起きている時間 (こまめにタップして所持数は溢れない想定)
SLEEP_HOURS = 8              # 寝ている時間 (タップできない。所持数が満杯になると食材が取れず、スキル判定も止まる)

# ---------------------------------------------------------------- 名前解決

POKEMON_BY_JA = {p["name_ja"]: p for p in DATA["pokemon"]}
POKEMON_BY_EN = {p["name_en"]: p for p in DATA["pokemon"]}
ING_JA2EN = {v["ja"]: k for k, v in DATA["ingredients"].items()}
NATURE_JA2EN = {v: k for k, v in DATA["natures"].items()}
SUBSKILL_JA2EN = {v: k for k, v in DATA["subskills"].items()}

NATURE_UP = {
    "speed": ["Lonely", "Adamant", "Naughty", "Brave"],
    "energy": ["Bold", "Impish", "Lax", "Relaxed"],
    "ing": ["Modest", "Mild", "Rash", "Quiet"],
    "skill": ["Calm", "Gentle", "Careful", "Sassy"],
    "exp": ["Timid", "Hasty", "Jolly", "Naive"],
}
NATURE_DOWN = {
    "speed": ["Bold", "Modest", "Calm", "Timid"],
    "energy": ["Lonely", "Mild", "Gentle", "Hasty"],
    "ing": ["Adamant", "Impish", "Careful", "Jolly"],
    "skill": ["Naughty", "Lax", "Rash", "Naive"],
    "exp": ["Brave", "Relaxed", "Quiet", "Sassy"],
}
NATURE_EFFECT_JA = {"speed": "おてつだいスピード", "energy": "げんき回復量", "ing": "食材おてつだい確率",
                    "skill": "メインスキル発生率", "exp": "EXP獲得量"}

# RP計算用のスキル値 (pokesleep-tool PokemonRp.skillValue)
SKILL_RP_VALUE = {
    ("Charge Strength S", "Charge Strength S (Random)"): [400, 569, 785, 1083, 1496, 2066, 2842],
    ("Charge Energy S",): [400, 569, 785, 1083, 1496, 2066, 2656],
    ("Charge Energy S (Moonlight)",): [560, 797, 1099, 1516, 2094, 2892],
    ("Charge Strength S (Stockpile)", "Skill Copy (Transform)", "Skill Copy (Mimic)"):
        [600, 853, 1177, 1625, 2243, 3099, 3984],
    ("Charge Strength M",): [880, 1251, 1726, 2383, 3290, 4546, 6252],
    ("Energy for Everyone S",): [1120, 1593, 2197, 3033, 4187, 5785],
    ("Cooking Assist S (Bulk Up)",): [1144, 1627, 2244, 3098, 4277, 5910, 7596],
    ("Energy for Everyone S (Berry Juice)",): [1220, 1735, 2392, 3303, 4559, 6299],
    ("Helper Boost",): [2800, 3902, 5273, 6975, 9317, 12438],
    ("Berry Burst (Draco Meteor)",): [2380, 3385, 4670, 6445, 8898, 12294],
    ("Berry Burst (Disguise)", "Berry Burst", "Energy for Everyone S (Lunar Blessing)"):
        [1400, 1991, 2747, 3791, 5234, 7232],
    ("Charge Strength M (Bad Dreams)",): [2400, 3313, 4643, 6441, 8864, 11878, 14072],
    ("Energizing Cheer S",): [766, 1089, 1502, 2074, 2863, 3956],
    ("Energizing Cheer S (Heal Pulse)",): [1600, 2300, 3180, 4417, 6113, 8462],
    ("Versatile",): [1280, 1651, 2126, 2783, 3690, 5056, 6463, 8033],
    ("Dream Shard Magnet S (Aura Sphere)",): [1040, 1479, 2040, 2816, 3888, 5372, 6905, 8543],
    ("Berry Zone (Psystrike)",): [2450, 3383, 4733, 6550, 8994, 12028],
}
SKILL_RP_DEFAULT = [880, 1251, 1726, 2383, 3290, 4546, 5843, 7303]

INGREDIENT_G = [
    1.0, 1.003, 1.007, 1.011, 1.016, 1.021, 1.027, 1.033, 1.039, 1.046,
    1.053, 1.061, 1.069, 1.077, 1.085, 1.094, 1.104, 1.114, 1.124, 1.134,
    1.145, 1.156, 1.168, 1.18, 1.192, 1.205, 1.218, 1.231, 1.245, 1.259,
    1.274, 1.288, 1.303, 1.319, 1.335, 1.351, 1.368, 1.385, 1.402, 1.42,
    1.439, 1.457, 1.477, 1.496, 1.517, 1.537, 1.558, 1.58, 1.602, 1.625,
    1.648, 1.671, 1.696, 1.72, 1.745, 1.771, 1.798, 1.824, 1.852, 1.88,
    1.927, 1.975, 2.024, 2.075, 2.127, 2.18, 2.235, 2.29, 2.348, 2.406,
    2.466, 2.527, 2.589, 2.653, 2.718, 2.784, 2.852, 2.921, 2.991, 3.062,
    3.135, 3.209, 3.285, 3.361, 3.439, 3.519, 3.599, 3.681, 3.764, 3.849,
    3.935, 4.022, 4.11, 4.2, 4.291, 4.383, 4.477, 4.572, 4.668, 4.766,
]


def fail(msg):
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


def normalize(s):
    s = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)  # ひらがな→カタカナ
    return s.replace(" ", "").replace("　", "").replace("（", "(").replace("）", ")")


def resolve(value, table, label):
    """日本語/英語名を正規名(英語キー)に解決。曖昧なら候補を出して終了。"""
    if value in table.values():
        return value
    if value in table:
        return table[value]
    norm = {normalize(k): v for k, v in table.items()}
    if normalize(value) in norm:
        return norm[normalize(value)]
    cands = difflib.get_close_matches(value, list(table.keys()), n=5, cutoff=0.4)
    fail(f"{label}「{value}」が見つかりません。候補: {', '.join(cands) or 'なし'}")


def find_pokemon(name):
    if name in POKEMON_BY_EN:
        return POKEMON_BY_EN[name]
    en = resolve(name, {k: v["name_en"] for k, v in POKEMON_BY_JA.items()}, "ポケモン")
    return POKEMON_BY_EN[en]


def ing_ja(en):
    return DATA["ingredients"][en]["ja"]


# ---------------------------------------------------------------- 個体の正規化

def parse_individual(raw):
    if "name" not in raw or "level" not in raw:
        fail("name と level は必須です")
    p = find_pokemon(raw["name"])
    level = int(raw["level"])
    nature = resolve(raw["nature"], NATURE_JA2EN, "せいかく") if raw.get("nature") else None
    subskills = [resolve(s, SUBSKILL_JA2EN, "サブスキル") for s in raw.get("subskills", [])]
    if len(subskills) > 5:
        fail("サブスキルは最大5つです")

    ings = raw.get("ingredients", [])
    if len(ings) > 3:
        fail("食材は最大3枠です")
    resolved_ings = []
    for slot, v in enumerate(ings):
        opts = p["ingredients"][slot]
        if v in ("A", "B", "C"):
            idx = "ABC".index(v)
            if p["mythical"] or idx >= len(opts):
                fail(f"{slot + 1}枠目に {v} は指定できません")
            resolved_ings.append(opts[idx]["name"])
            continue
        en = resolve(v, ING_JA2EN, "食材")
        if en not in [o["name"] for o in opts]:
            fail(f"{p['name_ja']}の{slot + 1}枠目(Lv{INGREDIENT_UNLOCK[slot]})に"
                 f"{ing_ja(en)}は出ません。選択肢: {', '.join(ing_ja(o['name']) for o in opts)}")
        resolved_ings.append(en)
    if not resolved_ings:
        resolved_ings = [p["ingredients"][0][0]["name"]]

    return {
        "name": p["name_ja"],
        "name_en": p["name_en"],
        "level": level,
        "nature": DATA["natures"][nature] if nature else None,
        "subskills": [DATA["subskills"][s] for s in subskills],
        "ingredients": [ing_ja(i) for i in resolved_ings],
        "skill_level": raw.get("skill_level"),
        "rp": raw.get("rp"),
        "ribbon": raw.get("ribbon", 0),
        "evolution_count": raw.get("evolution_count"),
        "nickname": raw.get("nickname", ""),
        "memo": raw.get("memo", ""),
    }


# ---------------------------------------------------------------- 計算

def js_round(v):
    """JavaScript の Math.round 相当 (Python の round は偶数丸め)"""
    return math.floor(v + 0.5)


def trunc(v, n):
    N = 10 ** n
    return math.floor(round(v * N, 6)) / N


def nature_effect(nature_ja):
    if not nature_ja:
        return None, None
    en = NATURE_JA2EN[nature_ja]
    up = next((k for k, v in NATURE_UP.items() if en in v), None)
    down = next((k for k, v in NATURE_DOWN.items() if en in v), None)
    return up, down


def berry_strength(ptype, level):
    b0 = DATA["berry_base_strength"][ptype]
    return max(b0 + level - 1, js_round(1.025 ** (level - 1) * b0))


def ribbon_factor(p, ribbon):
    left = p["evolutionLeft"]
    if left == 0:
        return 1
    if ribbon >= 4:
        return {2: 0.75, 1: 0.88}[left]
    if ribbon >= 2:
        return {2: 0.89, 1: 0.95}[left]
    return 1


RIBBON_CARRY = {0: 0, 1: 1, 2: 3, 3: 6, 4: 8}
INVENTORY_LEVEL = {"Inventory Up S": 1, "Inventory Up M": 2, "Inventory Up L": 3}


def nature_factors(up, down):
    return (0.9 if up == "speed" else 1.075 if down == "speed" else 1,
            1.2 if up == "ing" else 0.8 if down == "ing" else 1,
            1.2 if up == "skill" else 0.8 if down == "skill" else 1)


def subskill_key(active_en):
    """計算に効くサブスキルの要約: (スピード段階, 食材段階, スキル段階, きのみの数S, 所持数段階, おてつだいボーナス)"""
    return (active_en.count("Helping Speed S") + 2 * active_en.count("Helping Speed M"),
            active_en.count("Ingredient Finder S") + 2 * active_en.count("Ingredient Finder M"),
            active_en.count("Skill Trigger S") + 2 * active_en.count("Skill Trigger M"),
            int("Berry Finding S" in active_en),
            sum(INVENTORY_LEVEL.get(s, 0) for s in active_en),
            int("Helping Bonus" in active_en))


def base_frequency(p, level, nat_speed, speed_n, ribbon, helping_bonus):
    sub = speed_n * 0.07
    if helping_bonus:
        sub = min(sub + 0.05, 0.35)
    freq = p["frequency"] * trunc((501 - level) / 500 * nat_speed * ribbon_factor(p, ribbon) * (1 - sub), 4)
    if level == 10 and p["frequency"] == 2600 and not helping_bonus:
        freq -= 0.1  # ゲーム内の丸め誤差補正 (pokesleep-tool 準拠)
    return freq


@functools.lru_cache(maxsize=None)
def _night_dp(steps, carry, berry_p, berry_count, ing_usage):
    """睡眠中(タップなし)の所持数DP。ing_usage = ((確率, 個数), ...) 枠ごと。
    各ステップ後の累積: 満杯確率, きのみ期待数, 枠ごとの食材期待数 を返す。"""
    state = [0.0] * carry
    state[0] = 1.0
    cum_full, cum_berry, cum_ing = [0.0], [0.0], [tuple(0.0 for _ in ing_usage)]
    usage = [(berry_p, berry_count, None)] + [(q, c, k) for k, (q, c) in enumerate(ing_usage)]
    for _ in range(steps):
        nxt = [0.0] * carry
        full = berry = 0.0
        ing = [0.0] * len(ing_usage)
        for used, prob in enumerate(state):
            if prob == 0:
                continue
            for q, c, k in usage:
                tp = prob * q
                if tp == 0:
                    continue
                if k is None:
                    berry += c * tp
                    add = c
                else:
                    add = min(c, carry - used)
                    ing[k] += add * tp
                nu = used + add
                if nu < carry:
                    nxt[nu] += tp
                else:
                    full += tp
        state = nxt
        cum_full.append(cum_full[-1] + full)
        cum_berry.append(cum_berry[-1] + berry)
        cum_ing.append(tuple(a + b for a, b in zip(cum_ing[-1], ing)))
    return cum_full, cum_berry, cum_ing


def _night_n(n, carry, berry_p, berry_count, ing_usage, skill_rate, skill_stock):
    cum_full, cum_berry, cum_ing = _night_dp(n, carry, berry_p, berry_count, ing_usage)
    sneaky = sum(cum_full[i] for i in range(n))  # 満杯後の「つまみぐい」回数
    # スキル判定は満杯になるまで。ストック上限 (スキル・オールタイプ2回、他1回)
    p = skill_rate
    once = twice = 0.0

    def add(prob, k):
        nonlocal once, twice
        none_k = (1 - p) ** k
        if skill_stock >= 2:
            once_k = k * p * (1 - p) ** (k - 1) if k > 0 else 0
            once += prob * once_k
            twice += prob * (1 - none_k - once_k)
        else:
            once += prob * (1 - none_k)

    for k in range(1, n):
        add(cum_full[k] - cum_full[k - 1], k)
    add(1 - cum_full[n - 1] if n > 0 else 1, n)
    return {
        "berries": cum_berry[n] + sneaky * berry_count,
        "ings": cum_ing[n],
        "skill": once + 2 * max(0.0, twice),
        "full_prob": cum_full[n],
        "sneaky": sneaky,
    }


def night(n, *args):
    """n (小数可) 回おてつだいした場合の夜の期待値。小数部は線形補間 (pokesleep-tool 準拠)"""
    lo, hi = math.floor(n), math.ceil(n)
    a = _night_n(lo, *args)
    if hi == lo:
        return a
    b = _night_n(hi, *args)
    f = n - lo
    return {k: (tuple(x + (y - x) * f for x, y in zip(a[k], b[k])) if isinstance(a[k], tuple)
                else a[k] + (b[k] - a[k]) * f) for k in a}


@functools.lru_cache(maxsize=None)
def compute(name_en, level, nat, sub, ings, ribbon, evo):
    """1日 (起きている16時間はこまめにタップ / 寝ている8時間はタップなし) の期待値"""
    p = POKEMON_BY_EN[name_en]
    nat_speed, nat_ing, nat_skill = nat
    speed_n, ing_n, skill_n, bfs, inv, hb = sub

    freq = base_frequency(p, level, nat_speed, speed_n, ribbon, hb)
    ing_rate = trunc(p["ingRate"] / 100 * nat_ing * (1 + ing_n * 0.18), 4)
    skill_rate = trunc(p["skillRate"] / 100 * nat_skill * (1 + skill_n * 0.18), 4)
    berry_rate = 1 - ing_rate
    berry_count = (2 if p["specialty"] in ("Berries", "All") else 1) + bfs
    carry = p["carryLimit"] + 5 * evo + RIBBON_CARRY[min(ribbon, 4)] + 6 * inv
    skill_stock = 2 if p["specialty"] in ("Skills", "All") else 1

    slots = [k for k, lv in enumerate(INGREDIENT_UNLOCK) if level >= lv and k < len(ings)]
    counts = tuple(next(o["count"] for o in p["ingredients"][k] if o["name"] == ings[k]) for k in slots)

    awake = AWAKE_HOURS * 3600 / freq
    asleep = SLEEP_HOURS * 3600 / freq
    nt = night(asleep, carry, berry_rate, berry_count,
               tuple((ing_rate / len(slots), c) for c in counts), skill_rate, skill_stock)

    berries = awake * berry_rate * berry_count + nt["berries"]
    per_ing = {}
    for k, c, night_cnt in zip(slots, counts, nt["ings"]):
        per_ing[ings[k]] = per_ing.get(ings[k], 0) + awake * ing_rate / len(slots) * c + night_cnt
    bstr = berry_strength(p["type"], level)
    return {
        "level": level,
        "help_sec": round(freq, 1),
        "helps_per_day": awake + asleep,
        "ing_rate": ing_rate,
        "skill_rate": skill_rate,
        "berry_count_per_help": berry_count,
        "berry_strength": bstr,
        "carry_limit": carry,
        "night_helps": asleep,
        "full_prob": nt["full_prob"],
        "sneaky": nt["sneaky"],
        "berries_per_day": berries,
        "berry_energy_per_day": berries * bstr,
        "ingredients_per_day": {ing_ja(k): v for k, v in per_ing.items()},
        "ingredient_total_per_day": sum(per_ing.values()),
        "skill_per_day": awake * skill_rate + nt["skill"],
        "night_skill": nt["skill"],
    }


def evolution_count(ind):
    """実際に進化させた回数 (進化ごとに最大所持数+5)。未入力なら種族の進化段階ぶん進化させたとみなす"""
    if ind.get("evolution_count") is not None:
        return int(ind["evolution_count"])
    return max(0, POKEMON_BY_EN[ind["name_en"]]["evolutionCount"])


def calc(ind, level=None):
    level = level or ind["level"]
    up, down = nature_effect(ind["nature"])
    active = [SUBSKILL_JA2EN[s] for s, lv in zip(ind["subskills"], SUBSKILL_UNLOCK) if level >= lv]
    r = dict(compute(ind["name_en"], level, nature_factors(up, down), subskill_key(active),
                     tuple(ING_JA2EN[i] for i in ind["ingredients"]), ind.get("ribbon", 0) or 0,
                     evolution_count(ind)))
    r["active_subskills"] = [DATA["subskills"][s] for s in active]
    return r


# ---------------------------------------------------------------- 必須サブスキル

def load_required():
    """{name_en: ((候補, ...), ...)}。各要素は「どれか1つあればよい」候補 (設定ファイルでは "A|B" と書く)"""
    if not REQUIRED.exists():
        return {}
    raw = json.loads(REQUIRED.read_text(encoding="utf-8"))
    out = {}
    for name, reqs in raw.items():
        en = find_pokemon(name)["name_en"]
        out[en] = tuple(tuple(resolve(a, SUBSKILL_JA2EN, "サブスキル") for a in r.split("|")) for r in reqs)
    return out


def required_for(name_en):
    return load_required().get(name_en, ())


def meets_required(subskills_en, required):
    return all(any(a in subskills_en for a in alts) for alts in required)


def required_ja(required):
    return " と ".join("|".join(DATA["subskills"][a] for a in alts) for alts in required)


def required_status(ind):
    """(必須の設定, 満たすか)。最終進化の設定を使う。設定なしなら ((), True)"""
    fin = final_form(ind)
    req = required_for(fin["name_en"])
    return req, meets_required([SUBSKILL_JA2EN[s] for s in ind["subskills"]], req)


# ---------------------------------------------------------------- 上位何%

GOLD = ["Berry Finding S", "Dream Shard Bonus", "Energy Recovery Bonus", "Helping Bonus",
        "Research EXP Bonus", "Skill Level Up M", "Sleep EXP Bonus"]
BLUE = ["Helping Speed M", "Ingredient Finder M", "Inventory Up L", "Inventory Up M",
        "Skill Level Up S", "Skill Trigger M"]
WHITE = ["Helping Speed S", "Ingredient Finder S", "Inventory Up S", "Skill Trigger S"]
# サブスキル1枠あたりの出現の重み。全サブスキル同じ確率でつく前提 (出現率を反映したい場合はここを変える)
SUBSKILL_WEIGHT = {s: 1.0 for s in GOLD + BLUE + WHITE}


@functools.lru_cache(maxsize=None)
def subskill_distribution(required=()):
    """5つのサブスキル(重複なし・重み付き非復元抽出)の組み合わせ確率を (subskill_key, 必須を満たすか) ごとに集計"""
    names = list(SUBSKILL_WEIGHT)
    w = [SUBSKILL_WEIGHT[n] for n in names]
    total = sum(w)
    prob = {0: 1.0}
    for _ in range(5):
        nxt = {}
        for mask, pr in prob.items():
            rest = total - sum(w[i] for i in range(len(names)) if mask >> i & 1)
            for i in range(len(names)):
                if not mask >> i & 1:
                    m = mask | 1 << i
                    nxt[m] = nxt.get(m, 0) + pr * w[i] / rest
        prob = nxt
    dist = {}
    for mask, pr in prob.items():
        chosen = [names[i] for i in range(len(names)) if mask >> i & 1]
        key = (subskill_key(chosen), meets_required(chosen, required))
        dist[key] = dist.get(key, 0) + pr
    return dist


def nature_distribution():
    dist = {}
    for en in DATA["natures"]:
        up = next((k for k, v in NATURE_UP.items() if en in v), None)
        down = next((k for k, v in NATURE_DOWN.items() if en in v), None)
        key = nature_factors(up, down)
        dist[key] = dist.get(key, 0) + 1 / len(DATA["natures"])
    return dist


PERCENTILE_METRICS = ["berry_energy_per_day", "ingredient_total_per_day", "skill_per_day"]


def percentile(ind, level=None):
    """同じポケモンのランダムな個体 (せいかく・サブスキル・食材の並び) の中で上位何%かを返す。
    必須サブスキルが設定されていれば、それを満たす個体は満たさない個体より常に上とみなす"""
    level = level or EVAL_LEVEL
    p = POKEMON_BY_EN[ind["name_en"]]
    mine = calc(ind, level)
    required = required_for(ind["name_en"])
    mine_ok = meets_required([SUBSKILL_JA2EN[s] for s in ind["subskills"]], required)
    if p["mythical"]:
        ing_dist = {tuple(ING_JA2EN[i] for i in ind["ingredients"]): 1.0}  # 幻は食材を自分で選ぶ
    else:
        combos = [()]
        for opts in p["ingredients"]:
            combos = [c + (o["name"],) for c in combos for o in opts]
        ing_dist = {c: 1 / len(combos) for c in combos}
    ribbon, evo = ind.get("ribbon", 0) or 0, evolution_count(ind)

    above = {m: 0.0 for m in PERCENTILE_METRICS}
    for nk, npr in nature_distribution().items():
        for (sk, ok), spr in subskill_distribution(required).items():
            if ok and not mine_ok:  # 必須を満たす個体はすべて上
                for m in PERCENTILE_METRICS:
                    above[m] += npr * spr
                continue
            if not ok and mine_ok:  # 必須を満たさない個体はすべて下
                continue
            for ik, ipr in ing_dist.items():
                r = compute(p["name_en"], level, nk, sk, ik, ribbon, evo)
                for m in PERCENTILE_METRICS:
                    if r[m] >= mine[m] * (1 - 1e-9):
                        above[m] += npr * spr * ipr
    return {m: v * 100 for m, v in above.items()}


def calc_rp(ind):
    """ゲーム内RPの再現 (スクショの読み取りミス検出用)"""
    p = POKEMON_BY_EN[ind["name_en"]]
    c = calc(ind)
    level = ind["level"]
    up, down = nature_effect(ind["nature"])
    active = [SUBSKILL_JA2EN[s] for s, lv in zip(ind["subskills"], SUBSKILL_UNLOCK) if level >= lv]
    freq = base_frequency(p, level, nature_factors(up, down)[0], subskill_key(active)[0],
                          ind.get("ribbon", 0) or 0, False)  # RPにはおてつだいボーナスを含めない
    help5 = 5 * trunc(3600 / freq, 2)

    ing_en = [ING_JA2EN[i] for i in ind["ingredients"]]
    energies = []
    for slot, lv in enumerate(INGREDIENT_UNLOCK):
        if level >= lv and slot < len(ing_en):
            cnt = next(o["count"] for o in p["ingredients"][slot] if o["name"] == ing_en[slot])
            energies.append(DATA["ingredients"][ing_en[slot]]["strength"] * cnt)
    ing_energy = energies[0] if len(energies) == 1 else math.floor(sum(energies) / len(energies))
    g = INGREDIENT_G[level - 1] if level - 1 < len(INGREDIENT_G) else 1

    ingredient_rp = trunc(help5 * c["ing_rate"] * ing_energy * g, 2)
    berry_rp = trunc(help5 * (1 - c["ing_rate"]) * c["berry_strength"] * c["berry_count_per_help"], 2)
    slv = ind.get("skill_level") or 1
    table = next((v for k, v in SKILL_RP_VALUE.items() if p["skill"] in k), SKILL_RP_DEFAULT)
    skill_rp = trunc(help5 * c["skill_rate"] * table[min(slv, len(table)) - 1], 2)

    bonus = 1.08 if up == "energy" else 0.92 if down == "energy" else 1
    sub_bonus = 1
    for s in c["active_subskills"]:
        en = SUBSKILL_JA2EN[s]
        sub_bonus += {"Inventory Up L": 0.181, "Inventory Up M": 0.139, "Inventory Up S": 0.071}.get(en, 0)
        if en in ("Helping Bonus", "Sleep EXP Bonus", "Dream Shard Bonus", "Research EXP Bonus",
                  "Energy Recovery Bonus"):
            sub_bonus += 0.221
    bonus = trunc(bonus * sub_bonus, 2)
    return js_round((round(ingredient_rp * 100, 6) + round(berry_rp * 100, 6) + round(skill_rp * 100, 6))
                 * round(bonus * 100, 6) / 10000)


def final_form(ind):
    """進化で性格・サブスキル・食材枠(A/B/C)は引き継がれるので、最終進化に換算した個体を返す。
    進化先が1通りに決まらない(イーブイ等)・進化しない場合はそのまま返す。"""
    p = POKEMON_BY_EN[ind["name_en"]]
    if p["evolutionLeft"] == 0 or p["ancestor"] is None:
        return ind
    finals = [q for q in DATA["pokemon"] if q["ancestor"] == p["ancestor"] and q["evolutionLeft"] == 0
              and q.get("form") == p.get("form")]
    if len(finals) != 1:
        return ind
    q = finals[0]
    ings = []
    for slot, name in enumerate(ind["ingredients"]):
        idx = [o["name"] for o in p["ingredients"][slot]].index(ING_JA2EN[name])
        ings.append(ing_ja(q["ingredients"][slot][idx]["name"]))
    evo = ind.get("evolution_count")
    if evo is not None:
        evo = int(evo) + q["evolutionCount"] - p["evolutionCount"]
    return {**ind, "name": q["name_ja"], "name_en": q["name_en"], "ingredients": ings, "ribbon": 0,
            "evolution_count": evo}


# ---------------------------------------------------------------- 表示

def fmt(v, d=1):
    return f"{v:,.{d}f}"


def main_metric(p):
    return {"Berries": "berry_energy_per_day", "Ingredients": "ingredient_total_per_day",
            "Skills": "skill_per_day", "All": "berry_energy_per_day"}[p["specialty"]]


METRIC_JA = {
    "berry_energy_per_day": "きのみエナジー/日",
    "ingredient_total_per_day": "食材個数/日",
    "skill_per_day": "スキル回数/日",
}


def describe(ind):
    p = POKEMON_BY_EN[ind["name_en"]]
    up, down = nature_effect(ind["nature"])
    nat = (f"{ind['nature']} (▲{NATURE_EFFECT_JA[up]} ▼{NATURE_EFFECT_JA[down]})" if up
           else f"{ind['nature']} (補正なし)" if ind["nature"] else "未入力")
    lines = [
        f"## {p['name_ja']} Lv{ind['level']}" + (f"「{ind['nickname']}」" if ind.get("nickname") else ""),
        f"- とくい: {p['specialty_ja']} / きのみ: {p['berry']} / メインスキル: {p['skill_ja']}"
        + (f" Lv{ind['skill_level']}" if ind.get("skill_level") else ""),
        f"- せいかく: {nat}",
        "- サブスキル: " + " / ".join(
            f"{s}{'' if ind['level'] >= lv else f'(Lv{lv}〜)'}" for s, lv in zip(ind["subskills"], SUBSKILL_UNLOCK)),
        "- 食材: " + " / ".join(
            f"{i}×{next(o['count'] for o in p['ingredients'][k] if o['name'] == ING_JA2EN[i])}"
            f"{'' if ind['level'] >= INGREDIENT_UNLOCK[k] else f'(Lv{INGREDIENT_UNLOCK[k]}〜)'}"
            for k, i in enumerate(ind["ingredients"])),
    ]
    return "\n".join(lines)


def stats_table(ind, levels):
    rows = [calc(ind, lv) for lv in levels]
    header = "| 項目 | " + " | ".join(f"Lv{r['level']}" for r in rows) + " |"
    sep = "|---|" + "---:|" * len(rows)
    body = [
        ("おてつだい時間(秒)", [fmt(r["help_sec"]) for r in rows]),
        ("おてつだい回数/日", [fmt(r["helps_per_day"]) for r in rows]),
        ("食材確率", [f"{r['ing_rate'] * 100:.1f}%" for r in rows]),
        ("スキル確率", [f"{r['skill_rate'] * 100:.2f}%" for r in rows]),
        ("最大所持数", [str(r["carry_limit"]) for r in rows]),
        ("夜(8h)のおてつだい回数", [fmt(r["night_helps"]) for r in rows]),
        ("朝までに所持数が満杯になる確率", [f"{r['full_prob'] * 100:.0f}%" for r in rows]),
        ("きのみ個数/日", [fmt(r["berries_per_day"]) for r in rows]),
        ("**きのみエナジー/日**", [fmt(r["berry_energy_per_day"], 0) for r in rows]),
        ("**食材個数/日**", [fmt(r["ingredient_total_per_day"]) for r in rows]),
        ("**スキル回数/日**", [fmt(r["skill_per_day"], 2) for r in rows]),
        ("　うち夜のスキル", [fmt(r["night_skill"], 2) for r in rows]),
    ]
    names = []
    for r in rows:
        for k in r["ingredients_per_day"]:
            if k not in names:
                names.append(k)
    for n in names:
        body.append((f"　{n}/日", [fmt(r["ingredients_per_day"].get(n, 0)) for r in rows]))
    return "\n".join([header, sep] + [f"| {k} | " + " | ".join(v) + " |" for k, v in body])


def load_records():
    if not RECORDS.exists():
        return []
    return json.loads(RECORDS.read_text(encoding="utf-8"))


def save_records(records):
    RECORDS.parent.mkdir(parents=True, exist_ok=True)
    RECORDS.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compare(ind, records, exclude_id=None):
    p = POKEMON_BY_EN[ind["name_en"]]
    ing_set = {i for i in ind["ingredients"]}
    groups = [
        ("berry", f"同じきのみ({p['berry']})", "berry_energy_per_day",
         lambda q: q["type"] == p["type"]),
        ("ing", "同じ食材を持つ個体", "ingredient_total_per_day",
         lambda q, r: bool(ing_set & set(r["ingredients"]))),
        ("skill", f"同じメインスキル({p['skill_ja']})", "skill_per_day",
         lambda q: q["skill"] == p["skill"]),
    ]
    # とくいに対応する比較を先頭に
    order = {"Berries": "berry", "All": "berry", "Ingredients": "ing", "Skills": "skill"}[p["specialty"]]
    groups.sort(key=lambda g: g[0] != order)

    out = []
    for key, title, metric, pred in groups:
        matched = []
        for r in records:
            if r["id"] == exclude_id:
                continue
            q = POKEMON_BY_EN[r["name_en"]]
            ok = pred(q, r) if key == "ing" else pred(q)
            if ok:
                matched.append(r)
        mark = "【とくい】" if key == order else ""
        if not matched:
            out.append(f"### {mark}{title}: 記録なし")
            continue
        out.append(f"### {mark}{title} — 比較指標: {METRIC_JA[metric]}")
        lines = ["| 個体 | " + " | ".join(f"Lv{lv}" for lv in COMPARE_LEVELS) + " | 判定 |",
                 "|---|" + "---:|" * len(COMPARE_LEVELS) + "---|"]
        mine = [calc(final_form(ind), lv)[metric] for lv in COMPARE_LEVELS]
        mine_req, mine_ok = required_status(ind)
        d = 2 if metric == "skill_per_day" else 0
        evo = f"→{final_form(ind)['name']}" if final_form(ind)["name"] != ind["name"] else ""
        lines.append(f"| **今回**{evo} | " + " | ".join(f"**{fmt(v, d)}**" for v in mine) + " | |")
        for r in matched:
            fr = final_form(r)
            theirs = [calc(fr, lv)[metric] for lv in COMPARE_LEVELS]
            diff = (mine[-1] - theirs[-1]) / theirs[-1] * 100 if theirs[-1] else 0
            verdict = "今回が強い" if diff > 1 else "前の方が強い" if diff < -1 else "ほぼ同等"
            their_req, their_ok = required_status(r)
            if fr["name_en"] != final_form(ind)["name_en"]:  # 必須サブスキルは同じ種族同士でだけ考慮
                mine_ok_here, their_ok = True, True
            else:
                mine_ok_here = mine_ok
            if mine_ok_here and not their_ok:
                verdict = "今回が強い(前は必須サブスキルなし)"
            elif their_ok and not mine_ok_here:
                verdict = "前の方が強い(今回は必須サブスキルなし)"
            evo = f"→{fr['name']}" if fr["name"] != r["name"] else ""
            label = f"#{r['id']} {r['name']}{evo}({r['status']}) {r['nature'] or ''}"
            if not their_ok:
                label += " ⚠️必須なし"
            lines.append(f"| {label} | " + " | ".join(fmt(v, d) for v in theirs)
                         + f" | {verdict} ({diff:+.1f}%) |")
        out.append("\n".join(lines))
    out.append(f"※ 判定は Lv{EVAL_LEVEL} の値で比較。最終進化に換算した値 (→ で表示)。進化先が複数あるポケモンは現在の姿のまま比較します。")
    return "\n\n".join(out)


# ---------------------------------------------------------------- コマンド

def read_input(path):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def cmd_lookup(args):
    p = find_pokemon(args.name)
    print(f"## {p['name_ja']} ({p['name_en']})")
    print(f"- とくい: {p['specialty_ja']} / タイプ: {DATA_TYPE_JA.get(p['type'], p['type'])} / きのみ: {p['berry']}")
    print(f"- メインスキル: {p['skill_ja']}")
    print(f"- 基礎おてつだい時間: {p['frequency']}秒 / 食材確率: {p['ingRate']}% / "
          f"スキル確率: {p['skillRate']}% / 最大所持数: {p['carryLimit']}")
    for slot, opts in enumerate(p["ingredients"]):
        choices = " / ".join(f"{'ABC'[i] if not p['mythical'] else '-'}:{ing_ja(o['name'])}×{o['count']}"
                             for i, o in enumerate(opts))
        print(f"- 食材 Lv{INGREDIENT_UNLOCK[slot]}枠: {choices}")


DATA_TYPE_JA = {
    "normal": "ノーマル", "fire": "ほのお", "water": "みず", "electric": "でんき", "grass": "くさ",
    "ice": "こおり", "fighting": "かくとう", "poison": "どく", "ground": "じめん", "flying": "ひこう",
    "psychic": "エスパー", "bug": "むし", "rock": "いわ", "ghost": "ゴースト", "dragon": "ドラゴン",
    "dark": "あく", "steel": "はがね", "fairy": "フェアリー",
}


def cmd_eval(args):
    ind = parse_individual(read_input(args.input))
    print(describe(ind))
    if ind.get("rp") is not None:
        rp = calc_rp(ind)
        ok = abs(rp - int(ind["rp"])) <= 1
        print(f"\nRPチェック: スクショ {ind['rp']} / 計算 {rp} → "
              + ("一致 ✅" if ok else "不一致 ⚠️ 読み取り内容(レベル・せいかく・サブスキル・食材・スキルLv)を確認してください"))
    levels = sorted({ind["level"], *COMPARE_LEVELS})
    print("\n### 1日あたりの期待値\n")
    print(stats_table(ind, levels))
    fin = final_form(ind)
    if fin["name"] != ind["name"]:
        print(f"\n### 最終進化({fin['name']})に換算した場合\n")
        print(stats_table(fin, sorted({ind["level"], *COMPARE_LEVELS})))
    print(f"\n※ 1日 = 起きている{AWAKE_HOURS}時間(こまめにタップ) + 寝ている{SLEEP_HOURS}時間(タップなし)。"
          "夜は所持数が満杯になると食材が取れなくなり(きのみの「つまみぐい」だけになる)スキル判定も止まる。"
          "スキルのストックは夜の間 1回まで(スキル・オールタイプは2回まで)。"
          "おてつだいボーナスは自分の分(5%)のみ。げんきによる速度変化・チームの他メンバーの効果は含まない。")
    fin_eval = final_form(ind)
    pct = percentile(fin_eval, EVAL_LEVEL)
    p = POKEMON_BY_EN[ind["name_en"]]
    main = {"Berries": ["berry_energy_per_day"], "Ingredients": ["ingredient_total_per_day"],
            "Skills": ["skill_per_day"], "All": PERCENTILE_METRICS}[p["specialty"]]
    evo = f"({fin_eval['name']}に進化した場合)" if fin_eval["name"] != ind["name"] else ""
    print(f"\n### 個体ランク: Lv{EVAL_LEVEL}{evo}の{POKEMON_BY_EN[fin_eval['name_en']]['name_ja']}の中で\n")
    print("| 指標 | 上位 | |")
    print("|---|---:|---|")
    for m in PERCENTILE_METRICS:
        mark = "**【とくい】**" if m in main else ""
        print(f"| {METRIC_JA[m]} | {'**' if mark else ''}{pct[m]:.1f}%{'**' if mark else ''} | {mark} |")
    print("\n※ せいかく(25種均等)・サブスキル(全17種が同じ確率)・食材の並び(均等)をすべての組み合わせで計算した順位。")
    req, ok = required_status(ind)
    fin_name = final_form(ind)["name"]
    raw_req = json.loads(REQUIRED.read_text(encoding="utf-8")) if REQUIRED.exists() else {}
    if fin_name not in raw_req:
        print(f"※ 必須サブスキル: {fin_name}は未確認 → ユーザーに必須サブスキルがあるか確認すること")
    if req:
        print(f"※ 必須サブスキル: {required_ja(req)} → "
              + ("満たしている ✅(満たさない個体より常に上として順位を計算)" if ok
                 else "満たしていない ⚠️(満たす個体すべてより下として順位を計算)"))
    print("\n" + compare(ind, load_records(), exclude_id=args.exclude_id))


def cmd_save(args):
    ind = parse_individual(read_input(args.input))
    records = load_records()
    new_id = max((r["id"] for r in records), default=0) + 1
    rec = {"id": new_id, "status": args.status, "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"), **ind}
    c = calc(ind, EVAL_LEVEL)
    rec[f"snapshot_lv{EVAL_LEVEL}"] = {k: round(c[k], 2) for k in METRIC_JA}
    records.append(rec)
    save_records(records)
    print(f"記録しました: #{new_id} {ind['name']} Lv{ind['level']} ({args.status})")


def cmd_list(args):
    records = load_records()
    if args.name:
        en = find_pokemon(args.name)["name_en"]
        records = [r for r in records if r["name_en"] == en]
    if not records:
        print("記録はありません")
        return
    print("| ID | ポケモン | Lv | 状態 | せいかく | サブスキル | 食材 | きのみE/日@80 | 食材個数/日@80 | スキル/日@80 |")
    print("|---:|---|---:|---|---|---|---|---:|---:|---:|")
    for r in records:
        c = calc(r, EVAL_LEVEL)
        print(f"| {r['id']} | {r['name']}{'「' + r['nickname'] + '」' if r.get('nickname') else ''} | "
              f"{r['level']} | {r['status']} | {r['nature'] or '-'} | {' / '.join(r['subskills'])} | "
              f"{' / '.join(r['ingredients'])} | {fmt(c['berry_energy_per_day'], 0)} | "
              f"{fmt(c['ingredient_total_per_day'])} | {fmt(c['skill_per_day'], 2)} |")


def cmd_update(args):
    records = load_records()
    rec = next((r for r in records if r["id"] == args.id), None)
    if rec is None:
        fail(f"#{args.id} は見つかりません")
    patch = read_input(args.input)
    base = {k: rec.get(k) for k in ("name", "level", "nature", "subskills", "ingredients", "skill_level",
                                     "rp", "ribbon", "evolution_count", "nickname", "memo")}
    base.update(patch)
    ind = parse_individual(base)
    rec.update(ind)
    if args.status:
        rec["status"] = args.status
    rec["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    c = calc(ind, EVAL_LEVEL)
    rec[f"snapshot_lv{EVAL_LEVEL}"] = {k: round(c[k], 2) for k in METRIC_JA}
    save_records(records)
    print(f"更新しました: #{rec['id']} {rec['name']} Lv{rec['level']} ({rec['status']})")


def cmd_delete(args):
    records = load_records()
    rest = [r for r in records if r["id"] != args.id]
    if len(rest) == len(records):
        fail(f"#{args.id} は見つかりません")
    save_records(rest)
    print(f"削除しました: #{args.id}")


def cmd_require(args):
    raw = json.loads(REQUIRED.read_text(encoding="utf-8")) if REQUIRED.exists() else {}
    if not args.name:
        if not raw:
            print("必須サブスキルの設定はありません")
        for name, reqs in raw.items():
            print(f"- {name}: {' と '.join(reqs) or '必須なし(確認済み)'}")
        return
    p = find_pokemon(args.name)
    if args.clear:
        raw.pop(p["name_ja"], None)
        print(f"{p['name_ja']}の必須サブスキルを解除しました")
    elif args.none:
        raw[p["name_ja"]] = []
        print(f"{p['name_ja']}: 必須サブスキルなし(確認済み)として記録しました")
    else:
        if not args.subskills:
            fail("サブスキルを指定してください (どれか1つでよい場合は \"A|B\")")
        reqs = ["|".join(DATA["subskills"][resolve(a, SUBSKILL_JA2EN, "サブスキル")] for a in r.split("|"))
                for r in args.subskills]
        raw[p["name_ja"]] = reqs
        print(f"{p['name_ja']}の必須サブスキル: {' と '.join(reqs)}")
    REQUIRED.parent.mkdir(parents=True, exist_ok=True)
    REQUIRED.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="ポケモンスリープ 個体評価・記録ツール")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("lookup"); s.add_argument("name"); s.set_defaults(f=cmd_lookup)
    s = sub.add_parser("eval"); s.add_argument("input"); s.add_argument("--exclude-id", type=int)
    s.set_defaults(f=cmd_eval)
    s = sub.add_parser("save"); s.add_argument("input")
    s.add_argument("--status", required=True, choices=["厳選完了", "キープ"]); s.set_defaults(f=cmd_save)
    s = sub.add_parser("list"); s.add_argument("--name"); s.set_defaults(f=cmd_list)
    s = sub.add_parser("update"); s.add_argument("id", type=int); s.add_argument("input")
    s.add_argument("--status", choices=["厳選完了", "キープ"]); s.set_defaults(f=cmd_update)
    s = sub.add_parser("delete"); s.add_argument("id", type=int); s.set_defaults(f=cmd_delete)
    s = sub.add_parser("require"); s.add_argument("name", nargs="?"); s.add_argument("subskills", nargs="*")
    s.add_argument("--clear", action="store_true")
    s.add_argument("--none", action="store_true", help="必須なしを確認済みとして記録")
    s.set_defaults(f=cmd_require)
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
