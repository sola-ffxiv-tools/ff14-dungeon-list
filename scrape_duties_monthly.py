#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每月爬取 FF14 副本分类/副本名，写入 MySQL（tipsff14.transcript_content）。

数据源优先级：
1. 灰机 Wiki 副本页「副本导航」
2. Garland Tools 国服浏览接口（garlandtools.cn，可稳定拿到中文名）
3. 本地 static/data/maze.json（兜底，保证表结构不空）

建议 crontab（每月 1 号凌晨 3 点）：
  0 3 1 * * cd /path/to/tipsff14 && /usr/bin/python3 scrape_duties_monthly.py >> logs/scrape_duties.log 2>&1

环境变量（可选）：
  MYSQL_HOST=127.0.0.1
  MYSQL_PORT=3306
  MYSQL_USER=root
  MYSQL_PASSWORD=your_password
  MYSQL_DATABASE=tipsff14
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOCAL_MAZE = ROOT / "static" / "data" / "maze.json"

HUIJI_URL = "https://ff14.huijiwiki.com/wiki/%E5%89%AF%E6%9C%AC"
GARLAND_INSTANCE_URL = "https://garlandtools.cn/db/doc/browse/chs/2/instance.json"

# 与现有 maze.json 一致的资料片等级分段（按 min_lvl）
EXPANSIONS: List[Tuple[str, int, int]] = [
    ("重生之境", 1, 50),
    ("苍穹之禁城", 51, 60),
    ("红莲之狂潮", 61, 70),
    ("暗影之逆焰", 71, 80),
    ("晓月之终途", 81, 90),
    ("金曦之遗辉", 91, 100),
]

# Garland Tools 的 type -> 是否按资料片拆分
SPLIT_BY_EXPANSION = {"迷宫挑战", "讨伐歼灭战", "大型任务"}

# 直接使用 type 作为大标题（与 maze.json 对齐）
PLAIN_TYPES = {
    "行会令",
    "绝境战",
    "诛灭战",
    "季节活动特殊迷宫",
    "深层迷宫",
    "特殊场景探索",
    "特殊迷宫探索",
    "假面狂欢",
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "tipsff14-monthly-scraper/1.0"
)


Category = Dict[str, Any]  # {"title": str, "list": [{"title": str}, ...]}


def _ssl_contexts() -> List[ssl.SSLContext]:
    contexts: List[ssl.SSLContext] = []
    try:
        import certifi  # type: ignore

        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    contexts.append(ssl.create_default_context())
    # 部分本机 Python 缺 CA 证书时兜底（仅爬虫脚本使用）
    insecure = ssl._create_unverified_context()
    contexts.append(insecure)
    return contexts


def http_get(url: str, timeout: int = 45) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last_err: Optional[Exception] = None
    for ctx in _ssl_contexts():
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError(f"http_get failed: {url}")


def load_local_maze() -> List[Category]:
    if not LOCAL_MAZE.exists():
        return []
    data = json.loads(LOCAL_MAZE.read_text(encoding="utf-8"))
    return normalize_categories(data)


def normalize_categories(data: Any) -> List[Category]:
    """统一成 [{title, list:[{title}]}]"""
    if not isinstance(data, list):
        return []
    out: List[Category] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        raw_list = item.get("list") or []
        if not title or not isinstance(raw_list, list):
            continue
        names = []
        seen = set()
        for x in raw_list:
            if isinstance(x, dict):
                n = str(x.get("title") or "").strip()
            else:
                n = str(x or "").strip()
            if not n or n in seen:
                continue
            seen.add(n)
            names.append({"title": n})
        out.append({"title": title, "list": names})
    return out


def expansion_of(level: int) -> str:
    for name, lo, hi in EXPANSIONS:
        if lo <= level <= hi:
            return name
    return EXPANSIONS[-1][0]


# ---------------- source 1: huiji wiki ----------------

def scrape_huiji_wiki() -> Optional[List[Category]]:
    """
    尝试解析灰机 Wiki「副本导航」。
    若遭遇 Cloudflare / 结构变化，返回 None。
    """
    try:
        html = http_get(HUIJI_URL)
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        print(f"[huiji] request failed: {e}")
        return None

    if "Just a moment" in html or "cf-chl" in html or "challenge-platform" in html:
        print("[huiji] blocked by Cloudflare challenge")
        return None

    # 常见结构：导航区块中的分类标题 + 后续副本链接文本
    # 兼容两种：带等级前缀「[15] 副本名」或纯链接文本
    section = html
    m = re.search(r"副本导航([\s\S]{200,})", html)
    if m:
        section = m.group(1)

    # 分类标题：迷宫挑战（重生之境） / 行会令 / 绝境战 ...
    cat_pat = re.compile(
        r"(迷宫挑战（[^）]+）|讨伐歼灭战（[^）]+）|大型任务（[^）]+）|"
        r"行会令|绝境战|诛灭战|季节活动特殊迷宫|深层迷宫|特殊场景探索|特殊迷宫探索|假面狂欢)"
    )
    # 副本名链接
    link_pat = re.compile(r'<a[^>]+title="([^"]+)"[^>]*>', re.I)

    categories: List[Category] = []
    current: Optional[Category] = None
    # 按出现顺序扫一遍粗文本（去标签后也试一次）
    textish = re.sub(r"<script[\s\S]*?</script>", " ", section, flags=re.I)
    textish = re.sub(r"<style[\s\S]*?</style>", " ", textish, flags=re.I)

    # 先用 HTML 顺序切块：遇到分类标题开启新块
    parts = re.split(
        r"(?=("
        r"迷宫挑战（[^）]+）|讨伐歼灭战（[^）]+）|大型任务（[^）]+）|"
        r"行会令|绝境战|诛灭战|季节活动特殊迷宫|深层迷宫|特殊场景探索|特殊迷宫探索|假面狂欢"
        r"))",
        textish,
    )

    skip_titles = {
        "副本",
        "副本导航",
        "编辑",
        "讨论",
    }

    for part in parts:
        part = part.strip()
        if not part:
            continue
        cm = cat_pat.match(part)
        if cm and len(part) < 40:
            if current and current["list"]:
                categories.append(current)
            current = {"title": cm.group(1), "list": []}
            continue
        if current is None:
            continue
        for lm in link_pat.finditer(part):
            name = lm.group(1).strip()
            name = re.sub(r"^\[\d+\]\s*", "", name)
            if not name or name in skip_titles or name == current["title"]:
                continue
            if cat_pat.fullmatch(name):
                continue
            if any(x["title"] == name for x in current["list"]):
                continue
            current["list"].append({"title": name})

    if current and current["list"]:
        categories.append(current)

    categories = normalize_categories(categories)
    if len(categories) < 5:
        print(f"[huiji] parse too few categories: {len(categories)}")
        return None
    print(f"[huiji] ok, categories={len(categories)}")
    return categories


# ---------------- source 2: garlandtools ----------------

def scrape_garlandtools() -> Optional[List[Category]]:
    try:
        raw = http_get(GARLAND_INSTANCE_URL)
        payload = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        print(f"[garland] request/parse failed: {e}")
        return None

    browse = payload.get("browse") or []
    if not browse:
        print("[garland] empty browse")
        return None

    buckets: Dict[str, List[str]] = {}

    for item in browse:
        name = str(item.get("n") or "").strip()
        typ = item.get("t")
        if not name or not typ:
            continue
        typ = str(typ).strip()
        lvl = int(item.get("min_lvl") or item.get("max_lvl") or 1)

        if typ in SPLIT_BY_EXPANSION:
            key = f"{typ}（{expansion_of(lvl)}）"
        elif typ in PLAIN_TYPES:
            key = typ
        else:
            # 金碟/对战/寻宝等当前 maze.json 未收录，跳过
            continue

        buckets.setdefault(key, [])
        if name not in buckets[key]:
            buckets[key].append(name)

    # 尽量按本地 maze.json 的分类顺序输出
    local = load_local_maze()
    order = [c["title"] for c in local] if local else sorted(buckets.keys())

    categories: List[Category] = []
    used = set()
    for title in order:
        names = buckets.get(title) or []
        if not names:
            continue
        categories.append({"title": title, "list": [{"title": n} for n in names]})
        used.add(title)

    for title, names in buckets.items():
        if title in used or not names:
            continue
        categories.append({"title": title, "list": [{"title": n} for n in names]})

    categories = normalize_categories(categories)
    if not categories:
        return None
    print(f"[garland] ok, categories={len(categories)}")
    return categories


def merge_with_local(remote: List[Category], local: List[Category]) -> List[Category]:
    """远程缺的分类，用本地补齐，保证与现有页面结构兼容。"""
    remote_map = {c["title"]: c for c in remote}
    local_map = {c["title"]: c for c in local}
    titles = []
    for c in local:
        if c["title"] not in titles:
            titles.append(c["title"])
    for c in remote:
        if c["title"] not in titles:
            titles.append(c["title"])

    out: List[Category] = []
    for t in titles:
        if t in remote_map and remote_map[t]["list"]:
            out.append(remote_map[t])
        elif t in local_map:
            out.append(local_map[t])
    return out


def scrape_all() -> Tuple[List[Category], str]:
    local = load_local_maze()

    huiji = scrape_huiji_wiki()
    if huiji:
        return merge_with_local(huiji, local), "huiji_wiki"

    garland = scrape_garlandtools()
    if garland:
        return merge_with_local(garland, local), "garlandtools"

    if local:
        print("[fallback] using local maze.json")
        return local, "local_fallback"

    raise RuntimeError("所有数据源均失败，且本地 maze.json 不存在")


# ---------------- MySQL ----------------

def mysql_config() -> Dict[str, Any]:
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", "tipsff14"),
        "charset": "utf8mb4",
        "autocommit": False,
    }


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `transcript_content` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `title` VARCHAR(128) NOT NULL COMMENT '大分类标题，对应 json 顶层 title',
  `list` JSON NOT NULL COMMENT '副本列表，对应 json 的 list，元素为 {"title":"..."}',
  `source` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '数据来源',
  `scraped_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '本次爬取时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_title` (`title`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='副本分类与副本名（与 maze.json 结构一致）';
"""


def save_to_mysql(categories: List[Category], source: str) -> None:
    try:
        import pymysql  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "缺少依赖 pymysql，请先执行: pip install -r requirements-scraper.txt"
        ) from e

    cfg = mysql_config()
    conn = pymysql.connect(**cfg)
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `{}` DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci".format(cfg["database"])
            )
            cur.execute("USE `{}`".format(cfg["database"]))
            cur.execute(CREATE_TABLE_SQL)

            upsert = """
            INSERT INTO `transcript_content` (`title`, `list`, `source`, `scraped_at`)
            VALUES (%s, CAST(%s AS JSON), %s, %s)
            ON DUPLICATE KEY UPDATE
              `list` = VALUES(`list`),
              `source` = VALUES(`source`),
              `scraped_at` = VALUES(`scraped_at`),
              `updated_at` = CURRENT_TIMESTAMP
            """
            for cat in categories:
                cur.execute(
                    upsert,
                    (
                        cat["title"],
                        json.dumps(cat["list"], ensure_ascii=False),
                        source,
                        scraped_at,
                    ),
                )
        conn.commit()
        print(f"[mysql] upsert ok, rows={len(categories)}, source={source}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def export_snapshot(categories: List[Category], source: str) -> Path:
    out_dir = ROOT / "logs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"transcript_content_{stamp}.json"
    path.write_text(
        json.dumps(
            {"source": source, "scraped_at": stamp, "data": categories},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[snapshot] {path}")
    return path


def main() -> int:
    print("=== tipsff14 monthly duty scrape ===")
    print("time:", datetime.now().isoformat(timespec="seconds"))
    categories, source = scrape_all()
    total_items = sum(len(c["list"]) for c in categories)
    print(f"scraped categories={len(categories)}, duties={total_items}, source={source}")

    export_snapshot(categories, source)

    dry = "--dry-run" in sys.argv
    if dry:
        print("[dry-run] skip mysql write")
        return 0

    save_to_mysql(categories, source)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[fatal]", exc, file=sys.stderr)
        raise
