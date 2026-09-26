"""records/ 配下の記録を、全ブランチのうち最後に更新されたものにそろえる。

記録はセッション(= ブランチ)ごとに更新・コミットされていくので、新しいセッションのブランチには
以前の記録が入っていないことがある。pokesleep.py / field_rank.py は記録を読む前に sync() を呼び、
git fetch したうえで各ブランチの記録ファイルのうち最後にコミットされたものを作業ツリーに書き出す。

- 作業ツリーに未コミットの変更があるファイルは、そちらを優先して上書きしない(警告だけ出す)
- git が使えない・fetch できない場合は、手元にあるものでそのまま続ける
- 環境変数 PS_NO_SYNC=1 で無効にできる
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
FILES = ["records/pokemon.json", "records/required_subskills.json"]
_done = {}


def _git(*args):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)


def _warn(msg):
    print(f"[記録の同期] {msg}", file=sys.stderr)


def _latest(rel, refs, cur):
    """rel を最後に更新したコミットのあるブランチ。(時刻, ref, 短縮ハッシュ, 件名) or None"""
    best = None
    for ref in refs:
        log = _git("log", "-1", "--format=%ct%x09%h%x09%s", ref, "--", rel).stdout.strip()
        if not log:
            continue
        ts, h, subj = log.split("\t", 2)
        # 同時刻なら今のブランチを優先
        key = (int(ts), ref in (cur, f"origin/{cur}"))
        if best is None or key > best[0]:
            best = (key, ref, h, subj)
    return None if best is None else (best[0][0], best[1], best[2], best[3])


def _committed_blobs(rel, refs):
    """rel がどこかのブランチで一度でもコミットされた内容 (blob ハッシュ) の集合"""
    out = _git("log", "--format=", "--raw", "--no-abbrev", *refs, "--", rel).stdout
    return {line.split()[3] for line in out.splitlines() if line.startswith(":")}


def sync(fetch=True, quiet=False):
    """記録ファイルを最新にそろえる。戻り値: {rel: 出どころの説明}"""
    if _done:
        return _done
    if os.environ.get("PS_NO_SYNC"):
        _done.update({rel: "同期なし (PS_NO_SYNC)" for rel in FILES})
        return _done
    try:
        if fetch:
            r = _git("fetch", "--quiet", "--prune", "origin")
            if r.returncode != 0:
                _warn(f"git fetch に失敗しました。手元にあるブランチだけで探します ({r.stderr.strip()})")
        cur = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        refs = [r for r in _git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").stdout.split()
                if not r.endswith("/HEAD") and r != "origin"]
    except (OSError, subprocess.TimeoutExpired) as e:
        _warn(f"git が使えないため同期しません ({e})")
        _done.update({rel: "手元のファイル (同期なし)" for rel in FILES})
        return _done

    for rel in FILES:
        path = REPO_ROOT / rel
        latest = _latest(rel, refs, cur)
        dirty = _git("status", "--porcelain", "--", rel).stdout.strip()
        if latest is None:
            _done[rel] = "手元のファイル" if path.exists() else "記録なし"
            continue
        ts, ref, h, subj = latest
        when = datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M")
        src = f"{ref} の {h}「{subj}」({when})"
        content = _git("show", f"{ref}:{rel}").stdout
        if dirty and path.exists() and path.read_text(encoding="utf-8") != content:
            # 以前に同期しただけ(どこかでコミット済みの内容)なら上書きしてよい。手で変えた内容なら残す
            local = _git("hash-object", "--", rel).stdout.strip()
            if local not in _committed_blobs(rel, refs):
                _warn(f"{rel} に未コミットの変更があるため、{src} を取り込みませんでした。"
                      "記録を変更したらコミット・プッシュしてください")
                _done[rel] = "手元の未コミットの変更"
                continue
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            if not quiet:
                _warn(f"{rel} を最新の {src} に更新しました")
        _done[rel] = src
    return _done
