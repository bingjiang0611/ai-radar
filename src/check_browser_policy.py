"""检查/修复 Codex Browser Use policy 是否允许 ai-radar browser-use 源。

默认优先检查当前 `CODEX_THREAD_ID` 对应的 session；带 `--fix` 时若该 policy
文件尚不存在，会先创建，再把启用的 browser-use 源域名移到 `[origins].allowed`。
"""

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = Path.home() / ".codex" / "browser" / "sessions"


def browser_origins():
    sources = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]
    origins = set()
    for s in sources:
        if s.get("parser") != "browser" or not s.get("enabled"):
            continue
        if s.get("fetch") in {"twitter-cli", "jina"}:
            continue
        u = urlsplit(s["url"])
        if u.scheme and u.netloc:
            origins.add(f"{u.scheme}://{u.netloc}")
            if u.netloc.startswith("www."):
                origins.add(f"{u.scheme}://{u.netloc[4:]}")
            else:
                origins.add(f"{u.scheme}://www.{u.netloc}")
    return sorted(origins)


def latest_session():
    files = sorted(SESSIONS.glob("*.toml"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def default_session(fix=False):
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if thread_id:
        path = SESSIONS / f"{thread_id}.toml"
        if fix or path.exists():
            return path
    return latest_session()


def load_origins(path):
    if not path.exists():
        return set(), set()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    origins = data.get("origins") or {}
    return set(origins.get("allowed") or []), set(origins.get("denied") or [])


def _toml_list(name, values):
    lines = [f"{name} = ["]
    lines += [f'    "{v}",' for v in sorted(values)]
    lines.append("]")
    return "\n".join(lines)


def update_origins_block(text, allowed, denied):
    block = "[origins]\n" + _toml_list("allowed", allowed) + "\n" + _toml_list("denied", denied) + "\n"
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "[origins]"), None)
    if start is None:
        suffix = "" if text.endswith("\n") or not text else "\n"
        return text + suffix + block
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("[") and lines[i].strip().endswith("]"):
            end = i
            break
    return "\n".join(lines[:start] + block.rstrip("\n").splitlines() + lines[end:]) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="把 ai-radar browser-use 域名移到 allowed")
    ap.add_argument("--session", type=Path, default=None, help="指定 browser session toml；默认取当前线程，其次取最新")
    args = ap.parse_args()

    required = set(browser_origins())
    path = args.session or default_session(args.fix)
    if path is None:
        print("browser_policy: no session file found", file=sys.stderr)
        return 3

    allowed, denied = load_origins(path)
    blocked = sorted(required & denied)
    missing = sorted(required - allowed - denied)
    fix_cmd = f"cd ~/IdeaProjects/vibecoding/ai-radar && .venv/bin/python src/check_browser_policy.py --fix --session {path}"
    if args.fix:
        allowed = allowed | required
        denied = denied - required
        try:
            SESSIONS.mkdir(parents=True, exist_ok=True)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(update_origins_block(text, allowed, denied), encoding="utf-8")
        except PermissionError as e:
            print(json.dumps({
                "session": str(path),
                "required": sorted(required),
                "blocked": blocked,
                "missing": missing,
                "ok": False,
                "error": str(e),
                "run_in_user_terminal": fix_cmd,
            }, ensure_ascii=False, indent=2), file=sys.stderr)
            return 3
        blocked = []
        missing = []

    print(json.dumps({
        "session": str(path),
        "required": sorted(required),
        "blocked": blocked,
        "missing": missing,
        "ok": not blocked and (args.fix or not missing),
        **({"run_in_user_terminal": fix_cmd} if blocked or missing else {}),
    }, ensure_ascii=False, indent=2))
    return 0 if not blocked and (args.fix or not missing) else 2


if __name__ == "__main__":
    raise SystemExit(main())
