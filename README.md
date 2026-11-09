# FF14 国服副本列表数据

用 GitHub Actions 从国服客户端解包仓库 [thewakingsands/ffxiv-datamining-cn](https://github.com/thewakingsands/ffxiv-datamining-cn)
拉取 CSV，生成副本列表 JSON，提交回本仓库并同步到 Gitee，供 App 直接读取。

- 不依赖任何第三方 API，运行时也不需要服务器/数据库
- 每周自动刷新一次，国服版本更新后可手动触发
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

### `keepalive` 分支（心跳，App 不需要读）

公共仓库的 scheduled workflow 在 60 天没有任何仓库活动后会被自动禁用
（[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)）。
为了保活又不污染 main 的历史，`keepalive` workflow 只在仓库长期闲置时，
往独立的 `keepalive` 分支推一个单 commit：

- 分支里只有一个 `status.json`，记录 `lastHeartbeatAt` 和阈值
- 每次都是孤儿 commit + force push，分支永远只有一个 commit
- 距上次仓库活动 ≥ `KEEPALIVE_THRESHOLD_DAYS`（默认 45）天才触发
- `main` 上只保留真正的数据更新提交

### App 读取地址

```text
# 主推：Gitee 镜像（国内快）
https://gitee.com/<GITEE_OWNER>/<GITEE_REPO>/raw/main/data/maze.json

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

# 2. 生成 data/maze.json、data/duties.json
python scripts/build_duties.py --input vendor --out data

# 3. 数据异常下降 / 分类被移除时会失败；确认无误可跳过保护
python scripts/build_duties.py --input vendor --out data --force
```

`vendor/` 已在 `.gitignore` 里，不会提交。

## 更新流水线

两个 workflow 都只跑在默认分支上。

### `update-duty-data`（每周）

1. 拉取 4 张上游 CSV（`ContentFinderCondition` / `ContentType` / `TerritoryType` / `ExVersion`）
2. 生成 JSON 并做校验
3. 内容有变化 → commit + 打 `data-*` tag，推送 GitHub
4. 同步 Gitee：**先比对远端 SHA，一致就跳过（无任何副作用），不一致才 force push**；
   上次同步失败也能在下次运行自动补齐

没有内容变化时不会产生任何提交。触发方式：

- 每周一 18:00 UTC（北京时间周二 02:00）自动执行
- 国服版本更新后，在 Actions 页面手动 `Run workflow`（可选填上游 ref）

### `keepalive`（每周）

- 每周四检查一次仓库最后活动时间，闲置超过阈值才更新 `keepalive` 分支心跳
- 仓库变量 `KEEPALIVE_THRESHOLD_DAYS`（默认 45）、`KEEPALIVE_BRANCH`（默认 `keepalive`）可调整
- 手动触发时可勾选 `force` 立即推一次心跳，用来验证配置

### 校验规则（`scripts/build_duties.py`）

- 字段缺失（上游改表结构）直接失败
- 全量 < 700 条、分类视图 < 400 条直接失败
- 相比上一版跌幅超过 10% 失败（防止上游抽风）
- 分类被移除失败
- 深层迷宫必须能聚合出 死者宫殿 / 天之御柱 / 正统优雷卡 / 朝圣交错路

## 设计取舍：数据放 `data/` 还是单独分支？

数据本身放在默认分支的 `data/` 目录，不单独建 `data` 分支：

- 数据量很小（两份 JSON 合计约 300 KB），一年十几次数据提交不会让仓库变重
- 代码、规则、数据在同一个 commit 里，`git revert` 一次就能回滚
- 维护面最小（Razor）：workflow 不用 checkout 两个分支，Gitee 只需要镜像 main
- 保活提交走独立的 `keepalive` 分支，不占用 main 的历史

如果以后数据体积变大，或想保护 main 只允许 PR 修改，再拆 `data` 分支也不迟。

## 仓库配置（一次性）

1. GitHub 新建仓库，默认分支设为 `main`
2. Gitee 新建目标仓库（空仓库即可，默认分支建议 `main`；workflow 用 force push 覆盖镜像）
3. GitHub 仓库 `Settings → Secrets and variables → Actions`：
   - **Secret** `GITEE_TOKEN`：Gitee「私人令牌」，需要仓库读写权限
   - **Variable** `GITEE_OWNER`：目标仓库的命名空间（个人用户名或组织名）
   - **Variable** `GITEE_REPO`：目标仓库名
   - **Variable** `GITEE_USER`：令牌所属账号，需对目标仓库有写权限
   - **Variable** `GITEE_BRANCH`：可选，默认 `main`
   - **Variable** `KEEPALIVE_THRESHOLD_DAYS`：可选，默认 `45`
   - **Variable** `KEEPALIVE_BRANCH`：可选，默认 `keepalive`
4. 把本目录的 `data/` 一起提交（首次发布会带着当前数据）
5. 到 Actions 手动跑一次，确认 Gitee 同步成功

> 组织名/仓库名全部通过 Variables 配置，fork 后改成自己的即可，代码里没有硬编码。
> 如果暂时不想接 Gitee，不配置这些变量即可，workflow 会跳过同步并给出 warning。

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
- `duties.json` 的 `unmappedContentTypes` 会列出它，日志里也有 `警告:` 提示
- 确认要进分类视图后，在 `scripts/rules.py` 里加一行映射，手动触发一次 workflow 即可

## 历史说明

早期方案（爬灰机 Wiki / Garland + MySQL）的 `scrape_duties_monthly.py`、
`init_transcript_content.sql`，以及参照用的根目录 `maze.json` 已从仓库移除，
需要的话可以从 git 历史里找回。

`category-icons.json` / `tactics-icons.json` 是 App 侧资源，按需保留或移到 App 仓库。

## 来源与版权

见 [NOTICE.md](NOTICE.md)。
