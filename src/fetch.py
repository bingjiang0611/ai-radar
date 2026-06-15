"""HTTP 抓取 + URL 归一化。

抓取用 curl 子进程（macOS 自带，对各站的 TLS / UA 拦截最稳，且零 pip 依赖）。
URL 归一化用于去重 hash：去掉追踪参数、统一 host 大小写、去 fragment 和尾部斜杠，
让同一篇文章带不同 utm 参数时算出同一个 hash。
"""

import subprocess
import sys
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# 追踪类 query 参数,去重前剥掉。utm_ 是前缀族;其余精确匹配——
# 旧版用 startswith("ref") 会误删 reference_id 等合法参数(漏判),故改精确集 + 列全 ref 系真追踪参数。
_STRIP_PREFIX = ("utm_",)
_STRIP_EXACT = {"fbclid", "gclid", "mc_cid", "mc_eid", "spm", "ref", "ref_src",
                "ref_url", "reflink", "igshid", "_hsenc"}


def fetch(url, timeout=30):
    """返回响应正文字符串；失败返回 None。"""
    try:
        r = subprocess.run(
            # -f：HTTP ≥400 时 curl 退非 0(否则 502 错误页 HTML 会被当正常 body 解析成 0 条,掩盖失败)
            ["curl", "-fsL", "-A", "Mozilla/5.0", url],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  超时: {url}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001 — 单个源失败不应中断整轮抓取
        print(f"  ⚠️  抓取出错 {url}: {e}", file=sys.stderr)
        return None


def resolve_url(url):
    """替换 URL 里的时间占位符，让"当前周/当天"类源不用每次手改：
    {week} → 当前 ISO 周(如 2026-W24)；{date} → 今天(2026-06-13)。
    """
    if "{" not in url:
        return url
    now = datetime.now()
    iso = now.isocalendar()  # (ISO 年, ISO 周, 星期)
    return url.replace("{week}", f"{iso[0]}-W{iso[1]:02d}").replace("{date}", now.strftime("%Y-%m-%d"))


# 硬付费墙域名:正文 Jina/直连都穿不过,抓到也只是摘要 stub → 抓取时整条跳过(只滤拿不到全文的)。
# 计量墙但服务端直出正文、直连能抓全文的(如 wired.com / MIT Tech Review)不在此列,保留。
_HARD_PAYWALL = (
    "wsj.com", "nytimes.com", "ft.com", "bloomberg.com", "theinformation.com",
    "economist.com", "businessinsider.com", "seekingalpha.com", "barrons.com",
)


def is_paywalled(url):
    """URL 是否落在硬付费墙域名(正文不可得)。run.py/ingest.py 抓取时据此整条跳过。"""
    host = urlsplit(url if "//" in (url or "") else "//" + (url or "")).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in _HARD_PAYWALL)


def normalize_url(url):
    """归一化用于去重：剥追踪参数、**排序剩余参数**(顺序不同算同一 URL)、host 小写、去 fragment、去尾部斜杠。"""
    parts = urlsplit(url.strip())
    kept_query = sorted(
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in _STRIP_EXACT and not any(k.lower().startswith(p) for p in _STRIP_PREFIX)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        path,
        urlencode(kept_query),
        "",  # 丢弃 fragment
    ))
