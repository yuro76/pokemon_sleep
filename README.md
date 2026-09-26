# pokemon_sleep

ポケモンスリープ用の Claude Code スキル集。

## スキル

### `pokesleep-iv` — 個体評価・記録

ポケモン詳細画面のスクショを送ると、

1. せいかく・サブスキル・食材・メインスキルを読み取り(RPで読み取りミスをチェック)
2. Lv80時点のきのみエナジー/日・食材個数/日・スキル回数/日を計算(寝ている8時間はタップできず、所持数が満杯になると取りこぼす前提)
3. 同じポケモンの中で上位何%かを、とくい(きのみ/食材/スキル)に応じた指標で判定
4. 記録済みの個体(同じきのみ / 同じ食材 / 同じメインスキル)と比べて「今回が強い / 前の方が強い」を判定
5. 了承した個体だけを「厳選完了」「キープ」として `records/pokemon.json` に記録

使い方: このリポジトリで Claude Code を開き、スクショを添えて「この子を評価して」と送るだけ。
記録一覧は「記録を見せて」で表示できます。

詳細は [.claude/skills/pokesleep-iv/SKILL.md](.claude/skills/pokesleep-iv/SKILL.md)。

## コマンド

### `/field-ranking` — 次の週のフィールドランキング

次の週(月曜4:00〜)にどのフィールドへ行くのが良いかをランキングで出します。

1. イベントを確認(`data/events.json` + Web検索)。特定フィールドにメリットがあるイベントや、
   新規登場ポケモンが出るフィールドを優先
2. イベントがなければ、最新の厳選状況(全ブランチのうち最後に更新された `records/pokemon.json`)と各フィールドの出現ポケモンを照らし合わせ、
   **食材タイプで厳選完了できていないポケモン**が多く出るフィールドを優先

`/field-ranking 2026-10-05` のように週の開始日を、`/field-ranking アンバー渓谷は未開放` のように希望を付けられます。
中身は `python3 .claude/skills/pokesleep-iv/scripts/field_rank.py --help` を参照。

## データ

ポケモンの基礎データ・イベントは [nitoyon/pokesleep-tool](https://github.com/nitoyon/pokesleep-tool) (MIT License) から生成しています。
更新: `python3 .claude/skills/pokesleep-iv/scripts/update_data.py`

フィールドの出現ポケモンは [Serebii](https://www.serebii.net/pokemonsleep/locations/)
(取得できない環境では [YoheiOhto/sleepbox-compass](https://github.com/YoheiOhto/sleepbox-compass) (MIT License) の
Serebii 由来データ)から生成しています。ワカクサ本島は未収録です。
更新: `python3 .claude/skills/pokesleep-iv/scripts/update_fields.py`
