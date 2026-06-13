"""HTTP 抓取 + URL 归一化。

抓取用 curl 子进程（macOS 自带，对各站的 TLS / UA 拦截最稳，且零 pip 依赖）。
URL 归一化用于去重 hash：去掉追踪参数、统一 host 大小写、去 fragment 和尾部斜杠，
让同一篇文章带不同 utm 参数时算出同一个 hash。
"""

import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# 追踪类 query 参数前缀，去重前剥掉
_STRIP_QUERY_PREFIXES = ("utm_", "ref", "fbclid", "gclid", "mc_cid", "mc_eid", "spm")


def fetch(url, timeout=30):
    """返回响应正文字符串；失败返回 None。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "-A", "Mozilla/5.0", url],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  超时: {url}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001 — 单个源失败不应中断整轮抓取
        print(f"  ⚠️  抓取出错 {url}: {e}", file=sys.stderr)
        return None


def normalize_url(url):
    """归一化用于去重：剥追踪参数、host 小写、去 fragment、去尾部斜杠。"""
    parts = urlsplit(url.strip())
    kept_query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if not any(k.lower().startswith(p) for p in _STRIP_QUERY_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path,
        urlencode(kept_query),
        "",  # 丢弃 fragment
    ))
