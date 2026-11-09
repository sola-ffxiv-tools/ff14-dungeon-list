#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ffxiv-datamining-cn 的 CSV 构建成副本列表 JSON。

产出（默认写到 data/）：
    data/maze.json    兼容老结构 [{title, list:[{title}]}]，面板/App 直接可用
    data/duties.json  带 meta、分类、全量平铺数据的规范版本

输入（默认 vendor/，由 scripts/fetch_upstream.py 下载）：
    ContentFinderCondition.csv
    ContentType.csv
    TerritoryType.csv
    ExVersion.csv
    upstream.json     记录上游仓库/commit

用法：
    python scripts/build_duties.py --input vendor --out data
    python scripts/build_duties.py --input vendor --out data --force   # 跳过跌幅保护
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rules import (  # 同目录导入，直接 `python scripts/build_duties.py` 即可
    DEEP_DUNGEON_EXTRA_TYPE,
    DEEP_DUNGEON_FLOOR_TYPE,
    PLAIN_TYPES,
    SPECIAL_SCENE_TYPES,
    SPLIT_TYPES,
    Duty,
    build_maze_categories,
    known_content_types,
    to_maze_json,
)

SCHEMA_VERSION = 1

#: ContentType 表里没有名字（或名字是占位符）的类型，用业务口径补名
CONTENT_TYPE_NAME_OVERRIDES: dict[int, str] = {
    22: "季节活动特殊迷宫",
    39: "深层迷宫",
}

#: 硬性下限：低于这个数量说明上游结构或解析出问题了，直接失败
MIN_ALL_DUTIES = 700
MIN_MAZE_DUTIES = 400

#: 允许的最大跌幅（相对上一次发布），防止上游抽风把数据砍半
MAX_DROP_RATIO = 0.10

REQUIRED_CFC_FIELDS = (
    "#",
    "Name",
    "ContentType",
    "TerritoryType",
    "ClassJobLevel{Required}",
    "SortKey",
)


# ---------------------------------------------------------------- CSV 读取


def read_exd_csv(path: Path) -> tuple[dict[str, int], list[list[str]]]:
    """解析 FXIV CSV 导出格式。

    前 3 行分别是列序号、列名、类型，第 4 行开始是数据。
    返回 (列名 -> 下标, 数据行)。
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 4:
        raise ValueError(f"[build] CSV 行数异常: {path} ({len(rows)} 行)")

    positions: dict[str, int] = {}
    for index, name in enumerate(rows[1]):
        if name and name not in positions:
            positions[name] = index
    return positions, rows[3:]


def cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return row[index]


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_content_type_names(path: Path) -> dict[int, str]:
    positions, rows = read_exd_csv(path)
    names: dict[int, str] = {}
    for row in rows:
        type_id = to_int(cell(row, positions["#"]), -1)
        if type_id < 0:
            continue
        names[type_id] = cell(row, positions["Name"]).strip()
    return names


def load_expansions(path: Path) -> dict[int, str]:
    positions, rows = read_exd_csv(path)
    expansions: dict[int, str] = {}
    for row in rows:
        expansion_id = to_int(cell(row, positions["#"]), -1)
        name = cell(row, positions["Name"]).strip()
        if expansion_id < 0 or not name:
            continue
        expansions[expansion_id] = name
    return expansions


def load_territory_expansions(path: Path) -> dict[int, int]:
    positions, rows = read_exd_csv(path)
    territories: dict[int, int] = {}
    for row in rows:
        territory_id = to_int(cell(row, positions["#"]), -1)
        if territory_id < 0:
            continue
        territories[territory_id] = to_int(cell(row, positions["ExVersion"]), 0)
    return territories


def content_type_label(type_id: int, names: dict[int, str]) -> str:
    if type_id in CONTENT_TYPE_NAME_OVERRIDES:
        return CONTENT_TYPE_NAME_OVERRIDES[type_id]
    name = names.get(type_id, "").strip()
    # 上游偶尔用 "●XBM" 这种占位名，不往 App 里塞
    if name and not name.startswith("●"):
        return name
    return f"其他内容（type {type_id}）"


def load_duties(
    cfc_path: Path,
    territory_expansions: dict[int, int],
    expansion_names: dict[int, str],
    content_type_names: dict[int, str],
) -> list[Duty]:
    positions, rows = read_exd_csv(cfc_path)
    missing = [field for field in REQUIRED_CFC_FIELDS if field not in positions]
    if missing:
        raise ValueError(
            f"[build] ContentFinderCondition.csv 缺少字段 {missing}，"
            f"上游表结构可能变了。现有字段: {sorted(positions)}"
        )

    duties: list[Duty] = []
    seen_ids: set[int] = set()
    for row in rows:
        name = cell(row, positions["Name"]).strip()
        if not name:
            continue  # 256 行无名字的占位行，直接跳过

        duty_id = to_int(cell(row, positions["#"]), 0)
        if duty_id <= 0 or duty_id in seen_ids:
            continue
        seen_ids.add(duty_id)

        content_type = to_int(cell(row, positions["ContentType"]), 0)
        territory = to_int(cell(row, positions["TerritoryType"]), 0)
        expansion_id = territory_expansions.get(territory)
        expansion = expansion_names.get(expansion_id) if expansion_id is not None else None

        duties.append(
            Duty(
                id=duty_id,
                name=name,
                content_type=content_type,
                level=to_int(cell(row, positions["ClassJobLevel{Required}"]), 0),
                territory=territory,
                sort_key=to_int(cell(row, positions["SortKey"]), 0),
                expansion_id=expansion_id,
                expansion=expansion,
                content_type_name=content_type_label(content_type, content_type_names),
            )
        )
    return duties


# ---------------------------------------------------------------- 输出


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def flat_duty(duty: Duty) -> dict:
    return {
        "id": duty.id,
        "name": duty.name,
        "contentType": duty.content_type,
        "contentTypeName": duty.content_type_name,
        "level": duty.level,
        "expansion": duty.expansion,
        "territory": duty.territory,
        "sortKey": duty.sort_key,
    }


def write_json(path: Path, payload: object) -> None:
    """原子写，避免 Actions 在写入中途中断留下半个文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- 校验


def load_previous_counts(data_dir: Path) -> tuple[dict | None, list[str]]:
    path = data_dir / "duties.json"
    if not path.exists():
        return None, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[build] 读取上一次 duties.json 失败，跳过对比: {exc}", file=sys.stderr)
        return None, []
    categories = payload.get("categories") or []
    titles = [c.get("title") for c in categories if isinstance(c, dict)]
    return payload.get("counts") or {}, [t for t in titles if isinstance(t, str)]


def load_previous_order(data_dir: Path) -> dict[str, list[str]]:
    """上一版 maze.json 的名字顺序，用于保持显示顺序稳定。"""
    path = data_dir / "maze.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[build] 读取上一次 maze.json 失败，跳过顺序继承: {exc}", file=sys.stderr)
        return {}
    order: dict[str, list[str]] = {}
    for category in payload:
        if not isinstance(category, dict):
            continue
        title = category.get("title")
        items = category.get("list") or []
        if not title or not isinstance(items, list):
            continue
        order[title] = [
            item["title"]
            for item in items
            if isinstance(item, dict) and isinstance(item.get("title"), str)
        ]
    return order


def apply_previous_order(categories: list[dict], previous_order: dict[str, list[str]]) -> None:
    """沿用上一版顺序；新出现的副本按 id 追加到该分类末尾。"""
    for category in categories:
        previous = previous_order.get(category["title"])
        if not previous:
            continue
        rank = {name: index for index, name in enumerate(previous)}
        category["duties"].sort(
            key=lambda duty: (
                0,
                rank[duty["name"]],
            )
            if duty["name"] in rank
            else (1, duty["id"])
        )


def content_signature(categories: list[dict], duties: list[dict]) -> str:
    """内容指纹：用来判断这次跑出来的数据和上一版是否完全一样。

    只比较"内容"（分类顺序、id、名字、等级等），不比较时间戳；
    内容没变就不重写文件，避免每月产生一次无意义的提交和 Gitee 推送。
    """
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "categories": categories,
        "duties": duties,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def read_previous_payload(data_dir: Path) -> dict | None:
    path = data_dir / "duties.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[build] 读取上一次 duties.json 失败，跳过对比: {exc}", file=sys.stderr)
        return None
    return payload if isinstance(payload, dict) else None


def load_previous_signature(data_dir: Path) -> str:
    payload = read_previous_payload(data_dir)
    if not payload or not (data_dir / "maze.json").exists():
        return ""
    return content_signature(
        payload.get("categories") or [],
        payload.get("duties") or [],
    )


def read_previous_status(data_dir: Path) -> dict:
    path = data_dir / "status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def collect_unmapped(duties: list[Duty]) -> list[dict]:
    """找出规则未覆盖的 ContentType。

    这些内容会进入全量数据，但不会出现在分类视图里（maze.json）。
    上游新增类型时，这里会列出来，提醒维护者去 rules.py 补映射。
    """
    known = known_content_types()
    buckets: dict[int, dict] = {}
    for duty in duties:
        if duty.content_type in known:
            continue
        entry = buckets.setdefault(
            duty.content_type,
            {
                "id": duty.content_type,
                "name": duty.content_type_name,
                "count": 0,
            },
        )
        entry["count"] += 1
    return [buckets[content_type] for content_type in sorted(buckets)]


def print_unmapped_warning(unmapped: list[dict]) -> None:
    if not unmapped:
        return
    print(
        "[build] 警告: 发现规则未覆盖的 ContentType（已进入全量数据，但不会进入分类视图）:",
        file=sys.stderr,
    )
    for item in unmapped:
        print(
            f"  - type {item['id']} {item['name']!r}: {item['count']} 条；"
            f"如需进分类视图，请更新 scripts/rules.py",
            file=sys.stderr,
        )


def write_status(
    out_dir: Path,
    upstream: dict,
    counts: dict,
    data_version: str,
    unmapped: list[dict],
    content_changed: bool,
    last_content_change_at: str,
    now: datetime,
) -> None:
    """心跳文件：每次运行都会更新 lastCheckedAt。

    GitHub 公共仓库的定时任务在 60 天无仓库活动后会被自动禁用，
    每月提交一次 status.json 就是最小的"保活"活动；
    同时它也方便排查"上次检查是什么时候、上游到哪个 commit"。
    """
    payload = {
        "lastCheckedAt": utc_iso(now),
        "lastContentChangeAt": last_content_change_at,
        "contentChanged": content_changed,
        "dataVersion": data_version,
        "upstream": {
            "repo": upstream.get("repo", "thewakingsands/ffxiv-datamining-cn"),
            "ref": upstream.get("ref", "master"),
            "commit": str(upstream.get("commit") or ""),
        },
        "counts": counts,
        "unmappedContentTypes": unmapped,
    }
    write_json(out_dir / "status.json", payload)


def validate(
    categories: list[dict],
    duties: list[Duty],
    previous_counts: dict | None,
    previous_titles: list[str],
    force: bool,
) -> None:
    errors: list[str] = []

    if len(duties) < MIN_ALL_DUTIES:
        errors.append(f"全量副本数异常偏少: {len(duties)} < {MIN_ALL_DUTIES}")
    maze_total = sum(len(category["duties"]) for category in categories)
    if maze_total < MIN_MAZE_DUTIES:
        errors.append(f"分类视图副本数异常偏少: {maze_total} < {MIN_MAZE_DUTIES}")
    if len({duty.id for duty in duties}) != len(duties):
        errors.append("全量数据存在重复 id")
    if any(not duty.name.strip() for duty in duties):
        errors.append("存在空名字的副本")

    titles = [category["title"] for category in categories]
    if len(set(titles)) != len(titles):
        errors.append("分类标题重复")

    required_titles = {
        "行会令",
        "绝境战",
        "诛灭战",
        "季节活动特殊迷宫",
        "深层迷宫",
        "特殊场景探索",
        "特殊迷宫探索",
        "假面狂欢",
    }
    missing_titles = sorted(required_titles - set(titles))
    if missing_titles:
        errors.append(f"缺少分类: {missing_titles}")
    for label in SPLIT_TYPES.values():
        if not any(title.startswith(f"{label}（") for title in titles):
            errors.append(f"缺少按资料片拆分的分类: {label}")

    deep = next((c for c in categories if c["title"] == "深层迷宫"), None)
    deep_names = {item["name"] for item in (deep or {}).get("duties", [])}
    expected_deep = {"死者宫殿", "天之御柱", "正统优雷卡", "朝圣交错路"}
    if not expected_deep.issubset(deep_names):
        errors.append(f"深层迷宫聚合异常，缺少: {sorted(expected_deep - deep_names)}")

    seen_names: set[tuple[str, str]] = set()
    for category in categories:
        for item in category["duties"]:
            key = (category["title"], item["name"])
            if key in seen_names:
                errors.append(f"分类 {category['title']} 内副本名重复: {item['name']}")
            seen_names.add(key)

    if previous_counts and not force:
        previous_maze = int(previous_counts.get("mazeDuties") or 0)
        previous_all = int(previous_counts.get("allDuties") or 0)
        if previous_all and len(duties) < previous_all * (1 - MAX_DROP_RATIO):
            errors.append(
                f"全量副本数较上次大幅下降: {previous_all} -> {len(duties)}"
            )
        if previous_maze and maze_total < previous_maze * (1 - MAX_DROP_RATIO):
            errors.append(
                f"分类视图副本数较上次大幅下降: {previous_maze} -> {maze_total}"
            )
        removed = sorted(set(previous_titles) - set(titles))
        if removed:
            errors.append(f"分类被移除（疑似规则/上游异常）: {removed}（可用 --force 跳过）")

    if errors:
        print("[build] 校验失败：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)


# ---------------------------------------------------------------- 入口


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 FF14 副本列表 JSON")
    parser.add_argument("--input", default="vendor", help="CSV 输入目录（默认 vendor/）")
    parser.add_argument("--out", default="data", help="JSON 输出目录（默认 data/）")
    parser.add_argument("--force", action="store_true", help="跳过跌幅/分类移除保护")
    args = parser.parse_args()

    input_dir = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    upstream_path = input_dir / "upstream.json"
    upstream: dict = {}
    if upstream_path.exists():
        upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    upstream_commit = str(upstream.get("commit") or "")

    content_type_names = load_content_type_names(input_dir / "ContentType.csv")
    expansion_names = load_expansions(input_dir / "ExVersion.csv")
    territory_expansions = load_territory_expansions(input_dir / "TerritoryType.csv")
    duties = load_duties(
        input_dir / "ContentFinderCondition.csv",
        territory_expansions,
        expansion_names,
        content_type_names,
    )

    categories = build_maze_categories(duties)
    apply_previous_order(categories, load_previous_order(out_dir))
    maze_payload = to_maze_json(categories)
    maze_total = sum(len(category["list"]) for category in maze_payload)
    unmapped = collect_unmapped(duties)
    print_unmapped_warning(unmapped)

    previous_payload = read_previous_payload(out_dir)
    previous_counts, previous_titles = load_previous_counts(out_dir)
    validate(categories, duties, previous_counts, previous_titles, args.force)

    flat_duties = [flat_duty(duty) for duty in sorted(duties, key=lambda d: d.id)]
    signature = content_signature(categories, flat_duties)
    now = utc_now()
    counts = {
        "mazeCategories": len(categories),
        "mazeDuties": maze_total,
        "allDuties": len(duties),
    }

    if signature == load_previous_signature(out_dir):
        previous_status = read_previous_status(out_dir)
        last_content_change_at = (
            previous_status.get("lastContentChangeAt")
            or (previous_payload or {}).get("generatedAt")
            or utc_iso(now)
        )
        data_version = str((previous_payload or {}).get("dataVersion") or "")
        write_status(
            out_dir,
            upstream,
            counts,
            data_version,
            unmapped,
            False,
            str(last_content_change_at),
            now,
        )
        print("[build] 内容无变化，仅更新 data/status.json 心跳")
        return 0

    # dataVersion 跟着内容走：内容变了才变，App 可以拿它当缓存 key
    signature_short = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:7]
    data_version = f"{now:%Y.%m.%d}-{signature_short}"

    duties_payload = {
        "schemaVersion": SCHEMA_VERSION,
        "dataVersion": data_version,
        "generatedAt": utc_iso(now),
        "source": {
            "repo": upstream.get("repo", "thewakingsands/ffxiv-datamining-cn"),
            "ref": upstream.get("ref", "master"),
            "commit": upstream_commit,
            "fetchedAt": upstream.get("fetchedAt"),
        },
        "counts": counts,
        "unmappedContentTypes": unmapped,
        "categories": categories,
        "duties": flat_duties,
    }

    write_json(out_dir / "maze.json", maze_payload)
    write_json(out_dir / "duties.json", duties_payload)
    write_status(
        out_dir,
        upstream,
        counts,
        data_version,
        unmapped,
        True,
        utc_iso(now),
        now,
    )

    print(f"[build] upstream commit: {upstream_commit or '(unknown)'}")
    print(f"[build] categories: {len(categories)}")
    print(f"[build] maze duties: {maze_total}")
    print(f"[build] all duties: {len(duties)}")
    for category in categories:
        print(f"[build]   {category['title']}: {len(category['duties'])}")
    if previous_counts:
        print(
            "[build] vs previous: "
            f"maze {previous_counts.get('mazeDuties')} -> {maze_total}, "
            f"all {previous_counts.get('allDuties')} -> {len(duties)}"
        )
    for name in ("maze.json", "duties.json", "status.json"):
        size = (out_dir / name).stat().st_size
        print(f"[build] wrote {out_dir / name} ({size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
