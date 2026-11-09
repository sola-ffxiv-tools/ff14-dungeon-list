# FF14 国服副本列表数据

用 GitHub Actions 从国服客户端解包仓库 [thewakingsands/ffxiv-datamining-cn](https://github.com/thewakingsands/ffxiv-datamining-cn)
拉取 CSV，生成副本列表 JSON，提交回本仓库并同步到 Gitee，供 App 直接读取。

- 不依赖任何第三方 API，运行时也不需要服务器/数据库
- 每月自动刷新一次，国服版本更新后可手动触发
- 数据全部来自游戏客户端，分类口径与 App 现有数据结构对齐

## 数据文件

### `data/maze.json`

兼容现有结构的分类视图，App 首选：

```json
[
  {
    "title": "迷宫挑战（重生之境）",
    "list": [{ "title": "监狱废墟托托·拉克千狱" }]
  }
]
```

26 个分类（顺序固定，新内容追加到分类末尾）：

| 分类 | 说明 |
| --- | --- |
| 迷宫挑战（重生之境 / 苍穹之禁城 / 红莲之狂潮 / 暗影之逆焰 / 晓月之终途 / 金曦之遗辉） | `ContentType=2`，按资料片拆分 |
| 行会令 | `ContentType=3` |
| 讨伐歼灭战（同上 6 个资料片） | `ContentType=4`，按资料片拆分 |
| 大型任务（同上 6 个资料片） | `ContentType=5`，按资料片拆分 |
| 绝境战 | `ContentType=28` |
| 诛灭战 | `ContentType=37` |
| 季节活动特殊迷宫 | `ContentType=22`（官方表里无名字的类型） |
| 深层迷宫 | `ContentType=21` 的楼层条目聚合 + `ContentType=39` |
| 特殊场景探索 | 优雷卡(26) + 博兹雅(29) + 新月岛(38) |
| 特殊迷宫探索 | `ContentType=30` |
| 假面狂欢 | `ContentType=27` |

### `data/duties.json`

带版本信息和全量数据的规范版本（约 260 KB），推荐 App 用这个做搜索/展示：

```json
{
  "schemaVersion": 1,
  "dataVersion": "2026.11.02-ed9a884",
  "generatedAt": "2026-11-02T07:00:04Z",
  "source": { "repo": "thewakingsands/ffxiv-datamining-cn", "ref": "master", "commit": "..." },
  "counts": { "mazeCategories": 26, "mazeDuties": 450, "allDuties": 863 },
  "unmappedContentTypes": [],
  "categories": [
    {
      "title": "迷宫挑战（重生之境）",
      "contentType": [2],
      "expansion": "重生之境",
      "duties": [{ "id": 1, "name": "监狱废墟托托·拉克千狱" }]
    }
  ],
  "duties": [
    {
      "id": 1,
      "name": "监狱废墟托托·拉克千狱",
      "contentType": 2,
      "contentTypeName": "迷宫挑战",
      "level": 24,
      "expansion": "重生之境",
      "territory": 1039,
      "sortKey": 5
    }
  ]
}
```

- `categories`：与 `maze.json` 相同口径的分类视图；`id` 是 `ContentFinderCondition` 的稳定主键
- `duties`：**全量 863 条**有名字的内容，含对战、金碟、任务战斗、寻宝、深层迷宫楼层等，App 可按 `contentType` / `contentTypeName` 自行过滤
- 深层迷宫里那 4 条聚合项带 `"aggregated": true`（楼层条目合并而来），不是独立的游戏内容 id
- `dataVersion` = 日期 + 内容哈希：**内容不变不会变**，可以直接当 App 的缓存 key / 更新判断依据
- `unmappedContentTypes`：上游新增、但 `scripts/rules.py` 还没映射的类型列表（正常为空）。这些内容已经进 `duties`，只是暂时不在 `maze.json` 的分类视图里

### `data/status.json`

每次运行都会更新的心跳文件（约 0.5 KB），给维护者看，不建议 App 依赖：

```json
{
  "lastCheckedAt": "2026-11-09T08:45:06Z",
  "lastContentChangeAt": "2026-11-02T07:01:41Z",
  "contentChanged": false,
  "dataVersion": "2026.11.02-ed9a884",
  "upstream": { "repo": "thewakingsands/ffxiv-datamining-cn", "ref": "master", "commit": "2c6741c..." },
  "counts": { "mazeCategories": 26, "mazeDuties": 450, "allDuties": 863 },
  "unmappedContentTypes": []
}
```

它有两个作用：

1. 记录"上次检查时间 / 上游 commit / 是否真的有内容变化"
2. **保活**：GitHub 公共仓库的定时任务在 60 天没有任何仓库活动后会被自动禁用
   （[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)），
   每月提交一次 `status.json` 就是最小的活动量，保证定时任务一直有效

### App 读取地址

```text
# 主推：Gitee 镜像（国内快）
https://gitee.com/<GITEE_USER>/<GITEE_REPO>/raw/main/data/maze.json

# 备用：GitHub raw（国内可能不稳）
https://raw.githubusercontent.com/<GITHUB_USER>/<GITHUB_REPO>/main/data/maze.json
```

建议：启动时读一次并缓存，每 7 天检查一次更新；**App 内置一份兜底数据**，
网络失败时直接使用内置版本（开源 App 在构建时下载最新 JSON 打进包里即可）。

> Gitee 的 raw 地址会 302 到 `raw.giteeusercontent.com`（带签名参数），
> 客户端需要能跟随重定向。uni-app `uni.request` 在原生 App 上默认会跟随；
> 如果以后改成纯 H5 页面跑在浏览器里，跨域会被拦（Gitee 不给任意来源 CORS），
> 到时需要加对象存储（OSS/COS）或代理出口。
>
> 以后新增资料片时 `maze.json` 会多出「迷宫挑战（新资料片）」这类分类标题，
> App 的 `category-icons.json` 映射要留有默认图标兜底。

## 本地运行

无需第三方依赖，Python 3.11+ 即可。

```bash
# 1. 拉上游 CSV（国内网络可加 --api-only 走 GitHub contents API）
python scripts/fetch_upstream.py --out vendor
python scripts/fetch_upstream.py --api-only --out vendor

# 2. 生成 data/maze.json、data/duties.json、data/status.json
python scripts/build_duties.py --input vendor --out data

# 3. 数据异常下降 / 分类被移除时会失败；确认无误可跳过保护
python scripts/build_duties.py --input vendor --out data --force
```

`vendor/` 已在 `.gitignore` 里，不会提交。

## 更新流水线

`.github/workflows/update.yml` 流程：

1. 拉取 4 张上游 CSV（`ContentFinderCondition` / `ContentType` / `TerritoryType` / `ExVersion`）
2. 生成 JSON 并做校验
3. 内容有变化 → commit + 打 tag；只是心跳 → commit 不打 tag
4. 推送 GitHub，并同步到 Gitee 同名仓库（整仓镜像）

即使内容没变，每次也会更新 `data/status.json`（心跳）并提交一次：

- GitHub 公共仓库的定时任务在 60 天无仓库活动后会被自动禁用，心跳提交保证它一直有效
- Gitee 镜像也会跟着保持最新（否则内容不变时永远不会重新同步）
- 只有 `maze.json` / `duties.json` 真正变化时才会打 `data-*` tag

触发方式：

- 每月 1 日 18:00 UTC（北京时间 2 日 02:00）自动执行
- 国服版本更新后，在 Actions 页面手动 `Run workflow`（可选填上游 ref）

校验规则（`scripts/build_duties.py`）：

- 字段缺失（上游改表结构）直接失败
- 全量 < 700 条、分类视图 < 400 条直接失败
- 相比上一版跌幅超过 10% 失败（防止上游抽风）
- 分类被移除失败
- 深层迷宫必须能聚合出 死者宫殿 / 天之御柱 / 正统优雷卡 / 朝圣交错路

## 设计取舍：数据放 `data/` 还是单独分支？

目前选择放在默认分支的 `data/` 目录，而不是单独建 `data` 分支，理由：

- 数据量很小（三个文件合计约 300 KB），一年 12 次心跳提交不会让仓库变重
- 代码、规则、数据在同一个 commit 里，`git revert` 一次就能回滚"代码 + 数据"
- 维护面最小（Razor）：workflow 不用 checkout 两个分支，Gitee 也不用镜像额外分支
- **60 天自动禁用和放不放分支无关**：两种方式只要"没变化就不提交"都会踩坑，靠心跳解决

如果以后数据体积变大，或想保护 main 只允许 PR 修改，再拆 `data` 分支也不迟：
独立 workflow 推送 `data` 分支，App 的 URL 改一下分支路径即可。

## 仓库配置（一次性）

1. GitHub 新建仓库，默认分支设为 `main`
2. Gitee 新建同名仓库（空仓库即可，默认分支建议 `main`；workflow 用 force push 覆盖镜像）
3. GitHub 仓库 `Settings → Secrets and variables → Actions`：
   - **Secret** `GITEE_TOKEN`：Gitee「私人令牌」，需要仓库读写权限
   - **Variable** `GITEE_USER`：Gitee 用户名
   - **Variable** `GITEE_REPO`：Gitee 仓库名
   - **Variable** `GITEE_BRANCH`：可选，默认 `main`
4. 把本目录的 `data/` 一起提交（首次发布会带着当前数据）
5. 到 Actions 手动跑一次，确认 Gitee 同步成功

> 如果暂时不想接 Gitee，不配置上面这些变量即可，workflow 会跳过同步并给出 warning。

## 分类规则

所有业务口径集中在 `scripts/rules.py`，改需求只改这一个文件：

- 按资料片拆分：迷宫挑战 / 讨伐歼灭战 / 大型任务
- 合并到「特殊场景探索」：禁地优雷卡、天佑女王、蜃景幻界新月岛
- 「深层迷宫」把楼层条目（`死者宫殿 地下1～10层` 等）聚合成迷宫名
- 排除 `活动挑战N` 这类活动占位条目
- `FULL_ONLY_TYPES`：已知但只进全量数据的类型（对战 / 金碟 / 任务战斗等），不进分类视图
- 顺序：沿用上一版 `data/maze.json` 的顺序，新内容按 id 追加到所属分类末尾

## 未来新增内容怎么办？

| 情况 | 是否要改代码 | 说明 |
| --- | --- | --- |
| 现有类型下新增副本（新迷宫 / 新极神 / 新零式…） | ❌ 不用 | 自动出现在对应分类末尾，`dataVersion` 变化 |
| 新增资料片（如 8.0） | ❌ 不用 | `ExVersion.csv` 多一行后自动多出「迷宫挑战（新资料片）」等分类 |
| 新增一种 **ContentType**（例如新的难度体系） | ✅ 需要改 `scripts/rules.py` | 否则只进 `duties.json` 全量数据，不进 `maze.json` |
| 某条内容改名 | ❌ 不用 | 跟着上游走，新名字追加到分类末尾 |

新增 ContentType 时**不会报错中断**，流水线照常发布：

- 内容会出现在 `duties.json` 的 `duties` 里（`contentTypeName` 取自 `ContentType.csv`，表里没名字则显示 `其他内容（type N）`）
- `status.json` / `duties.json` 的 `unmappedContentTypes` 会列出它，日志里也有 `警告:` 提示
- 确认要进分类视图后，在 `scripts/rules.py` 里加一行映射，手动触发一次 workflow 即可

## 历史说明

早期方案（爬灰机 Wiki / Garland + MySQL）的 `scrape_duties_monthly.py`、
`init_transcript_content.sql`，以及参照用的根目录 `maze.json` 已从仓库移除，
需要的话可以从 git 历史里找回。

`category-icons.json` / `tactics-icons.json` 是 App 侧资源，按需保留或移到 App 仓库。

## 来源与版权

见 [NOTICE.md](NOTICE.md)。
