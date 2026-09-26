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

## データ

ポケモンの基礎データは [nitoyon/pokesleep-tool](https://github.com/nitoyon/pokesleep-tool) (MIT License) から生成しています。
更新: `python3 .claude/skills/pokesleep-iv/scripts/update_data.py`
