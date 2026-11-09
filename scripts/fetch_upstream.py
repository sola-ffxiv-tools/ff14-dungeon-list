#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 thewakingsands/ffxiv-datamining-cn 拉取构建副本列表所需的 CSV。

默认走 raw.githubusercontent.com；如果本机访问不了（国内常见），
自动降级到 GitHub contents API（base64）——API 有 60 次/小时的无认证限额，
本脚本最多用 5 次，没问题。

用法：
    python scripts/fetch_upstream.py --out vendor
    python scripts/fetch_upstream.py --ref master --out vendor
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UPSTREAM_REPO = "thewakingsands/ffxiv-datamining-cn"
UPSTREAM_BRANCH = "master"

# 构建只需要这 4 张表
FILES = (
    "ContentFinderCondition.csv",  # 全部副本条目
    "ContentType.csv",             # 类型 id -> 中文名
    "TerritoryType.csv",           # 地图 -> ExVersion（资料片）
    "ExVersion.csv",               # 资料片 id -> 中文名
)

USER_AGENT = "ff14-duty-data/1.0 (+https://github.com/%s)" % UPSTREAM_REPO


def http_get(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    """带重试的 GET：GitHub 偶发连接中断（IncompleteRead）重试一次基本就好。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定上游
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - 重试后仍失败再抛
            last_error = exc
            print(f"[fetch] GET 失败({attempt}/{retries}): {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"下载失败: {url}: {last_error}")


def fetch_raw(repo: str, ref: str, name: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/{name}"
    return http_get(url)


def fetch_contents_api(repo: str, ref: str, name: str) -> bytes:
    url = f"https://api.github.com/repos/{repo}/contents/{name}?ref={ref}"
    payload = json.loads(http_get(url).decode("utf-8"))
    content = payload.get("content")
    if not content:
        raise RuntimeError(f"API 返回内容为空: {name}")
    return base64.b64decode(content)


def resolve_commit(repo: str, ref: str) -> str:
    """拿上游 commit SHA，写进数据 meta，方便追溯。"""
    try:
        out = subprocess.check_output(
            ["git", "ls-remote", f"https://github.com/{repo}.git", f"refs/heads/{ref}"],
            text=True,
            timeout=60,
        )
        for line in out.splitlines():
            parts = line.split()
            if parts:
                return parts[0]
    except Exception as exc:  # noqa: BLE001 - 降级到 API
        print(f"[fetch] git ls-remote 失败: {exc}", file=sys.stderr)

    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    payload = json.loads(http_get(url).decode("utf-8"))
    return payload["sha"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 ffxiv-datamining-cn 的 CSV")
    parser.add_argument("--repo", default=UPSTREAM_REPO, help="上游仓库 owner/name")
    parser.add_argument("--ref", default=UPSTREAM_BRANCH, help="上游分支或 commit")
    parser.add_argument("--out", default="vendor", help="输出目录（默认 vendor/，不提交）")
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="跳过 raw.githubusercontent，直接走 contents API（国内网络/本地调试用）",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for name in FILES:
        source = "raw"
        try:
            if args.api_only:
                raise RuntimeError("--api-only")
            data = fetch_raw(args.repo, args.ref, name)
        except Exception as exc:  # noqa: BLE001 - 主动降级
            print(f"[fetch] raw 下载失败 ({name}): {exc}", file=sys.stderr)
            print(f"[fetch] 降级到 contents API 下载 {name}", file=sys.stderr)
            data = fetch_contents_api(args.repo, args.ref, name)
            source = "api"
        target = out_dir / name
        target.write_bytes(data)
        print(f"[fetch] {name} <- {source} ({len(data)} bytes)")

    try:
        commit = resolve_commit(args.repo, args.ref)
    except Exception as exc:  # noqa: BLE001 - 不阻塞构建，meta 里留空
        print(f"[fetch] 无法解析上游 commit: {exc}", file=sys.stderr)
        commit = ""

    meta = {
        "repo": args.repo,
        "ref": args.ref,
        "commit": commit,
        "fetchedAt": utc_now_iso(),
    }
    (out_dir / "upstream.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[fetch] upstream commit: {commit or '(unknown)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
