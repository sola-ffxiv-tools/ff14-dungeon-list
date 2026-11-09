# -*- coding: utf-8 -*-
"""FF14 副本列表的分类规则。

所有"业务口径"都集中在这里：新增分类、调整分组、排除某条内容，只改这个文件。
数据结构与 build_duties.py 解耦，方便单独测试。

口径来源：现有 maze.json 的 26 个分类，已经和国服客户端
ContentFinderCondition / ContentType / TerritoryType / ExVersion 逐条核对过。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

__all__ = [
    "Duty",
    "SPLIT_TYPES",
    "PLAIN_TYPES",
    "SPECIAL_SCENE_TYPES",
    "DEEP_DUNGEON_FLOOR_TYPE",
    "DEEP_DUNGEON_EXTRA_TYPE",
    "FULL_ONLY_TYPES",
    "EXCLUDE_NAME_PATTERNS",
    "build_maze_categories",
    "known_content_types",
    "to_maze_json",
]


@dataclass(frozen=True)
class Duty:
    """ContentFinderCondition 里一条有名字的副本（用 id 做主键）。"""

    id: int
    name: str
    content_type: int
    level: int
    territory: int
    sort_key: int
    expansion_id: Optional[int]
    expansion: Optional[str]
    content_type_name: Optional[str]


#: 按资料片拆分的大类：ContentType id -> 分类标题前缀
SPLIT_TYPES: dict[int, str] = {
    2: "迷宫挑战",
    4: "讨伐歼灭战",
    5: "大型任务",
}

#: 不拆分资料片的分类：ContentType id -> 分类标题
PLAIN_TYPES: list[tuple[int, str]] = [
    (3, "行会令"),
    (28, "绝境战"),
    (37, "诛灭战"),
    (22, "季节活动特殊迷宫"),  # ContentType 表里是空名，这里补上
    (27, "假面狂欢"),
    (30, "特殊迷宫探索"),
]

#: 特殊场景探索 = 禁地优雷卡(26) + 天佑女王(29) + 蜃景幻界新月岛(38)
SPECIAL_SCENE_TYPES: tuple[int, ...] = (26, 29, 38)

#: 深层迷宫：ContentFinderCondition 里是"死者宫殿 地下1～10层"这种楼层条目
DEEP_DUNGEON_FLOOR_TYPE = 21
DEEP_DUNGEON_EXTRA_TYPE = 39

#: 已知、但只进全量数据（duties.json 的 duties）不进分类视图的类型。
#: 这些是 PvP、金蝶、任务战斗、寻宝等，不属于"副本列表"的展示口径。
FULL_ONLY_TYPES: tuple[int, ...] = (6, 7, 9, 16, 19, 20, 23, 40)

#: 算不上"副本选择项"的条目（目前是活动占位）
EXCLUDE_NAME_PATTERNS: tuple[str, ...] = (r"^活动挑战\d+$",)

_EXCLUDE_RE = re.compile("|".join(EXCLUDE_NAME_PATTERNS))
# "死者宫殿 地下1～10层" / "天之御柱 1～10层" / "朝圣交错路 第1～10朝圣路"
_FLOOR_SUFFIX_RE = re.compile(r"\s+(?:地下)?\d+～\d+层$|\s+第\d+～\d+朝圣路$")


def known_content_types() -> set[int]:
    """规则已经覆盖的 ContentType id 集合。

    不在这个集合里的类型会进入全量数据，但不会进入分类视图；
    build_duties.py 会把它们列出来提醒维护者补规则。
    """
    types = set(SPLIT_TYPES)
    types.update(content_type for content_type, _ in PLAIN_TYPES)
    types.update(SPECIAL_SCENE_TYPES)
    types.update((DEEP_DUNGEON_FLOOR_TYPE, DEEP_DUNGEON_EXTRA_TYPE))
    types.update(FULL_ONLY_TYPES)
    return types


def _filter_usable(duties: Sequence[Duty]) -> list[Duty]:
    return [d for d in duties if not _EXCLUDE_RE.match(d.name)]


def _group_by_type(duties: Sequence[Duty]) -> dict[int, list[Duty]]:
    grouped: dict[int, list[Duty]] = {}
    for duty in duties:
        grouped.setdefault(duty.content_type, []).append(duty)
    return grouped


def _unique_by_name(duties: Sequence[Duty]) -> list[Duty]:
    """同一分类内按名字去重（保留 id 最小的一条）。

    ContentFinderCondition 存在同名不同 id 的条目（如"阿修罗歼灭战"），
    列表视图里去重，避免 App 里出现两条一模一样的名字；
    全量数据（duties.json 的 duties 数组）仍然保留每个 id。
    """
    seen: set[str] = set()
    out: list[Duty] = []
    for duty in sorted(duties, key=lambda d: d.id):
        if duty.name in seen:
            continue
        seen.add(duty.name)
        out.append(duty)
    return out


def _items(duties: Sequence[Duty]) -> list[dict]:
    return [{"id": d.id, "name": d.name} for d in duties]


def _category(
    title: str,
    content_types: Sequence[int],
    duties: Sequence[dict],
    expansion: Optional[str] = None,
) -> dict:
    return {
        "title": title,
        "contentType": list(content_types),
        "expansion": expansion,
        "duties": list(duties),
    }


def _split_category(content_type: int, duties: Sequence[Duty]) -> list[dict]:
    """按资料片拆分类，如 迷宫挑战（重生之境）。"""
    label = SPLIT_TYPES[content_type]
    unique = _unique_by_name(duties)
    groups: dict[int, list[Duty]] = {}
    for duty in unique:
        if duty.expansion_id is None or not duty.expansion:
            raise ValueError(
                f"[rules] 副本缺少资料片信息（TerritoryType.ExVersion 为空）: "
                f"id={duty.id} name={duty.name!r} territory={duty.territory}"
            )
        groups.setdefault(duty.expansion_id, []).append(duty)

    categories: list[dict] = []
    for expansion_id in sorted(groups):
        group = groups[expansion_id]
        expansion_name = group[0].expansion
        categories.append(
            _category(
                f"{label}（{expansion_name}）",
                (content_type,),
                _items(group),
                expansion=expansion_name,
            )
        )
    return categories


def _plain_category(title: str, content_type: int, duties: Sequence[Duty]) -> dict:
    return _category(title, (content_type,), _items(_unique_by_name(duties)))


def _special_scene_category(by_type: dict[int, list[Duty]]) -> dict:
    items: list[dict] = []
    seen: set[str] = set()
    for content_type in SPECIAL_SCENE_TYPES:
        for duty in sorted(by_type.get(content_type, []), key=lambda d: d.id):
            if duty.name in seen:
                continue
            seen.add(duty.name)
            items.append({"id": duty.id, "name": duty.name})
    return _category("特殊场景探索", SPECIAL_SCENE_TYPES, items)


def _deep_dungeon_category(by_type: dict[int, list[Duty]]) -> dict:
    """深层迷宫：楼层条目聚合回迷宫名，再补上类型 39 的两个特殊条目。"""
    groups: list[dict] = []
    index: dict[str, int] = {}
    for duty in sorted(by_type.get(DEEP_DUNGEON_FLOOR_TYPE, []), key=lambda d: d.id):
        base_name = _FLOOR_SUFFIX_RE.sub("", duty.name).strip()
        if base_name in index:
            continue
        index[base_name] = len(groups)
        groups.append({"id": duty.id, "name": base_name, "aggregated": True})

    extras = [
        {"id": duty.id, "name": duty.name, "aggregated": False}
        for duty in sorted(by_type.get(DEEP_DUNGEON_EXTRA_TYPE, []), key=lambda d: d.id)
    ]
    return _category(
        "深层迷宫",
        (DEEP_DUNGEON_FLOOR_TYPE, DEEP_DUNGEON_EXTRA_TYPE),
        groups + extras,
    )


def build_maze_categories(duties: Sequence[Duty]) -> list[dict]:
    """生成与现有 maze.json 同构的 26 个分类（顺序也保持一致）。"""
    usable = _filter_usable(duties)
    by_type = _group_by_type(usable)

    categories: list[dict] = []
    # 顺序与 maze.json 完全一致：
    # 迷宫挑战 ×6 -> 行会令 -> 讨伐歼灭战 ×6 -> 大型任务 ×6 -> 绝境战 -> 诛灭战
    # -> 季节活动特殊迷宫 -> 深层迷宫 -> 特殊场景探索 -> 特殊迷宫探索 -> 假面狂欢
    categories.extend(_split_category(2, by_type.get(2, [])))
    categories.append(_plain_category("行会令", 3, by_type.get(3, [])))
    categories.extend(_split_category(4, by_type.get(4, [])))
    categories.extend(_split_category(5, by_type.get(5, [])))
    categories.append(_plain_category("绝境战", 28, by_type.get(28, [])))
    categories.append(_plain_category("诛灭战", 37, by_type.get(37, [])))
    categories.append(_plain_category("季节活动特殊迷宫", 22, by_type.get(22, [])))
    categories.append(_deep_dungeon_category(by_type))
    categories.append(_special_scene_category(by_type))
    categories.append(_plain_category("特殊迷宫探索", 30, by_type.get(30, [])))
    categories.append(_plain_category("假面狂欢", 27, by_type.get(27, [])))
    return categories


def to_maze_json(categories: Sequence[dict]) -> list[dict]:
    """转成老结构：[{title, list:[{title}]}]，给 App / 老页面兼容用。"""
    return [
        {
            "title": category["title"],
            "list": [{"title": duty["name"]} for duty in category["duties"]],
        }
        for category in categories
    ]
