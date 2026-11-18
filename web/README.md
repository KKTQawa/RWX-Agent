# RWX-Agent 项目网站

一个不依赖框架、不需要构建的静态站点：首页介绍项目并播放实机录像，`results.html` 是完整对局与
Micro CASE 的公开评测账本。

- 网站：https://kktqawa.github.io/RWX-Agent/
- 评测结果：https://kktqawa.github.io/RWX-Agent/results.html
- 本项目源码：https://github.com/KKTQawa/RWX-Agent
- RWX 上游：https://github.com/yomi2539/RWX

## 页面结构

两个页面共用 `styles.css`（claymorphism 设计系统，亮/暗两套 token）与 `theme.js`（首屏前写
`data-theme`，记住选择）。

| 页面 | 区块 | 数据来源 |
| --- | --- | --- |
| `index.html` | hero → AGENT LOOP 条 → `#catalog` 五张科目卡 → `#progress` 进度追踪 → `#system` 系统能力 → `#recordings` 实机录像 → `#voices` 三条结论 → `#start` 快速开始 | 录像来自 `resource/matches.json`；目录卡、进度条、结论卡的数字由 `app.js` 从 `results.json` + `micro-results.json` 现算，HTML 里另有一份静态兜底 |
| `results.html` | KPI → `#overview-matrix` 总表（一行一个工具：模型 id / 工具 / 思考强度 / 提供方，横向是地图与 CASE，格子只写总分）→ `#match-ledger` 完整对局总表（14 列：展开 / 编号·对局 / Agent × 工具 / 地图·对手 / 结果 / total-v2.1 / Stage1 / Stage3 v3 / 偷袭 / 偷家 / 危险区死亡 / 资金空余 / Δ vs v2 / 评分时长，行内可展开逐项公式与材料）→ `#full-rules` 当前扣分细则（只有 Stage1-v2 与 Stage3-v2.1）→ `#micro-cases` 四个 CASE 的结果表与「扣分项 × 参与者」矩阵 → `#method` 现有结论 | `resource/results.json`、`resource/scoring.json`、`resource/micro-results.json`、`resource/match-ids.json`，由 `results.js` 渲染 |

数据流（四个生成器，产物都提交进仓库）：

```
evaluate/output/*            ──build_web_results_v2.js──▶ resource/results.json       ─┐
evaluate/output/micro/*      ──build_micro_results.py───▶ resource/micro-results.json ─┤
evaluate/config.json         ──build_scoring_v2.js──────▶ resource/scoring.json       ─┼─▶ results.js
resource/results.json        ──build_match_ids.py───────▶ resource/match-ids.json     ─┘

resource/matches.json ──▶ app.js（首页录像切换）
```

页面没有构建步骤，也没有前端依赖；改完直接刷新即可。颜色一律走 `styles.css` 里的 token，
不要在组件里写死色值，否则另一半主题会失配。

## 新增一场完整对局

页面上的「完整对局」全部来自 `resource/results.json`，不要手写这个 JSON。

### 1. 产出评测材料

按 [`evaluate/README.md`](../evaluate/README.md) 跑完评分，对局目录
`evaluate/output/<地图>-<日期>_<参与者>/` 下应当有：

| 文件 | 用途 |
| --- | --- |
| `meta.json` | 页面显示的身份信息，见下 |
| `stage_3/score.json` | 四类 Stage3 扣分与事件数（`breakdown[].items`） |
| `evaluation_v2.json`、`score_v2.json` | v2 评分，汇总进 `_v2-summary.json` |

`meta.json` 至少要写清楚：

- `models[]`：`provider`、`id`（模型 id，页面上原样显示）、`thinking`（推理强度）
- `tools`：`profile` 或 `kind`（Pi / DSH …）、`version`、`detail`
- `map.teams`：地图与阵营，用来算「地图 / 对手」列
- `timing.gameSeconds`：游戏内秒数；缺了页面会退回证据来源（`实时遥测` / `忠实回放重演`）
- `sessions`：多 Agent 局按会话数配对

这些字段由 [`evaluate/tools/match_materials.js`](../evaluate/tools/match_materials.js) 生成并维护，
不建议手改单个对局。

### 2. 重新生成总表

```powershell
node evaluate/tools/build_web_results_v2.js
```

它读 `evaluate/output/_v2-summary.json`、`_v21-summary.json` 与各局 `meta.json` / `stage_3/score.json`，
写出 `resource/results.json`（schema 3：`matches`、`overview`、`overview21`、`standard`、
`standard21`、`v1`、`ignored`、`method`）。每局的 `v21` 块由 `_v21-summary.json` 中相同
`relativePath` 的行合并而来。

### 3. 三种特殊情况

- **只进归档、不进榜**：`_v2-summary.json` 里 `archive !== 'current'` 的局不会出现在总表，
  这是刻意的「当前批次」口径，不要为了凑数改 `archive`。
- **老语料缺结构化 `meta.json`**：在 `build_web_results_v2.js` 顶部的 `ARCHIVE` 表补
  `date` / `agents` / `title`，脚本会给它填「历史原始工具」的说明。
- **材料不足或重放分叉**：由脚本写进 `ignored`（带 `title` / `reason` / `note`），页面只显示
  条数，不展示这些局，也不要手工补分。

### 4. 分配对局编号

```powershell
python -B web/tools/build_match_ids.py
```

只给 `archive === 'current'` 的局分配 `M01`、`M02`……；归档局不分配。已有编号不会被重排，
新局按日期追加下一个号，所以总表按分数排序、筛选或增删对局都不会改变任何一局的编号。
`resource/match-ids.json` 由这个脚本生成，不要手改。

脚本还会把同一个编号写进每局 `evaluate/output/<对局>/meta.json` 的 `matchId` 字段（已有相同值时不重写），
这样材料目录自己也带编号；`check_site.py` 会断言 `meta.json` 的 `matchId` 与 `match-ids.json` 一致，
两边不同步会直接报错。账本里每局还记了 `path`（相对 `evaluate/output` 的材料目录），
编号回写就是靠它对回去的。

### 5. 校验并查看

```powershell
python -B web/tools/check_site.py
```

通过后刷新 `results.html`：新局应出现在总表，KPI、平均分、最高分随之变化。首页的目录卡与
进度条也会跟着变；如果首页 HTML 里的静态兜底数字明显过时，顺手同步一下（JS 正常时不会用到）。

## 总表（模型 × 场景）

`results.html` 顶部 `#overview-matrix` 是跨「完整对局 / Micro CASE」的唯一一张对照表，由
`results.js` 从 `results.json` + `micro-results.json` + `match-ids.json` 现算，不额外落盘：

- **行**：一个工具一行，前四列是模型 id、工具（附 `RWX CLI` 等改造说明）、思考强度、提供方。
  表内只收 `deepseek-v4.1-flash`（思考强度 `high`、提供方 `opencode`）；人类单独占最后一行。
- **列**：先是「完整对局 · 地图」（同名地图的所有对局合到一列），再是四个 `CASE*-xxx`。
- **格子**：完整对局写 `stage1+stage3=总分`，CASE 写 `总分` 加 task id 与 seed（`2_7_4 · s1331`，
  不是只写 `type`；同一 CASE 的多次尝试再标「第 N 次」）。胜 / 负标记覆盖完整对局与 CASE 01/03/04；
  CASE 02 只有「按时建成 / 没建成」，不标胜负，但和 CASE 03 一样额外写「用时 m:ss」。
  完整对局的条目另带对局编号（`M07` 这种）与 AI 对手难度（`AI 中等`；多 AI / 2v2 写
  `2v2 · AI 困难`），难度取自 `meta.map.teams`。
- **留空**：该工具没有这个场景的对局时格子为空；脚本基线不入表。

### 新增一条记录

对局先按上面的流程进 `results.json`（完整对局）或 `micro-results.json`（CASE），再跑一次
`build_match_ids.py` 给新局编号，最后 `check_site.py`。总表不需要单独维护。

## 新增一场 CASE 对局

CASE 部分来自 `resource/micro-results.json`，由 `web/tools/build_micro_results.py` 扫描真实 run 生成，
规则（cap 与公式）从 `evaluate/micro/<CASE>/config.json` 渲染。

### 1. 目录布局

```
evaluate/output/micro/<CASE>/<display-name>/
├── meta.json            # 必需
├── result.json          # 必需：outcome、gameMs
├── <display-name>.replay # 回放，文件名与目录名相同
└── eval/metrics.json    # 必需：score.total / score.version / score.items[]
```

目录名就是 `meta.display_name`，例如
`CASE2-LTE 2_7_4 realtime · 20261114 17-59 · DeepSeek V4.1 Flash - Pi · s1331`：参与者（模型 - 工具，或
`baseline` / `human`）、task、track、seed 都写在路径里，不需要再翻 `meta.json` 才知道是谁跑的。引擎自己生成的
`<case>_<task>_<track>_s<seed>_<时间戳>` 只是采集时的临时名，收录时由
`evaluate/tools/stamp_micro_meta.py` 改名。

`meta.json` 关键字段：`mode`（`agent` / `human`）、`runner`（`agent` / `baseline` / `human`）、`task`、`seed`、
`models[{provider,id,thinking}]`、`tools[{profile}]`、`display_name`。脚本基线与人类局没有 `models`，靠
`runner` 声明身份。
`eval/metrics.json` 的 `score.items[]` 每项要有 `id` / `raw` / `cap` / `points`。

### 2. 每个 CASE 的记录构成

| 记录 | 来源 | 数量 |
| --- | --- | --- |
| 脚本基线 | `mode=agent` 且没有 `models` 的 run，取同 `task` 的最后一条 | 1 |
| 本地 Agent | 有 `models` 的 run，每个工具一条（CASE2 是 Pi + DSH） | 1 条以上 |
| 外部材料 | 脚本顶部 `EXTERNAL` 表（材料已不在仓库内，如 CASE1/3/4 的 DSH 局） | 0–1 |
| 人类 | `mode=human` 且同 `task` | 可多条 |

所以：

- **换一局本地 Agent**：把新 run 目录放进 `<CASE>/`，同时把旧的那条移出该目录（同工具只留最新一局；
  不同工具各留一条，脚本按 `models` 逐条出行）。
- **再加一条外部材料**：改 `EXTERNAL[case_id]` 的 `run` / `score` / `outcome` / `seconds` /
  `model` / `tool` / `items`（`raw, cap, points`），来源写进 `EXTERNAL_SOURCE`。目前每个 CASE
  只放一条外部记录，要放两条得改 `build_case()` 的拼装逻辑；材料已收进仓库的 CASE 不写 `EXTERNAL`
  （CASE2 的 DSH 局就是这样）。
- **新增第 5 个 CASE**：需要同时改 `CASES` 表（标签、标题、图、视频、环境说明）、
  `evaluate/micro/<CASE>/config.json`、`resource/cases/*.webp`、`resource/CASE*.mp4`、
  `check_site.py` 里的 `len(cases) == 4` 断言，以及首页 `#catalog` 的科目卡。

### 3. 重新生成并校验

```powershell
python -B web/tools/build_micro_results.py
python -B web/tools/check_site.py
```

生成器自带两条硬断言，任何一条不满足都会中止并打印具体 CASE / 记录：

- 记录里的每项 `cap` 必须等于 `config.json` 的 cap；
- `100 − Σpoints` 必须等于记录分数（±0.15）。

页面的矩阵列头取 `record.detail.split(" · ")[0]`，所以 `detail` 要以工具名（`Pi` / `DSH`）开头；
`check_site.py` 也会检查这一点。同一 CASE 有多次尝试时（`meta.attempt`），`detail` 写成
`Pi 02 · OpenCode`：列头因此能分开 `Pi 01` / `Pi 02`，而工具汇总仍按 `detail.split(" ")[0]` 归到 `Pi`。
结论卡的「四个 CASE 平均分」按 CASE 取均值（同一 CASE 的多次尝试先平均），所以一个 CASE 跑两次
不会在总分里占两份权重。

## 数据校验

`python -B web/tools/check_site.py` 是唯一入口，校验内容包括：

- 两页的本地链接、锚点、重复 id，以及 `theme.js` / 主题按钮是否存在
- `results.json`：schema、三套加权（`total-v2.1` / `total-v2` / `total-v1`）、v2.1 四项 cap 与
  `Δ`、`ignored` 计数、`v1` 冻结快照
- `scoring.json`：schema 2、只允许 `stage1` + `stage3v21` 两组、每项都要有公式与说明
- `micro-results.json`：四个 CASE、规则与记录 cap 一致、points 求和 = 分数、Agent 行的模型
  与工具标注
- `match-ids.json`：编号恰好覆盖当前批次的每一局、互不重复、形如 `M01`
- 录像清单：文件大小与 SHA-256、单文件 < 100 MB、站点总量 < 1 GB

`check_site.py` 不读 `evaluate/`（该目录不进版本库），所以分数一致性以仓库内的 JSON 为准。

## 约定

- **不写占位符**：页面不出现 `—`。数字要么来自评分产物，要么写成明确说明
  （`未记录` / `未评分窗口` / `材料只记录了评分窗口`）。
- **不手改产物 JSON**：`results.json`、`micro-results.json`、`scoring.json`、`match-ids.json`
  都由脚本生成；要改数字就改源材料并重跑生成器。
- **时间与单位**：分数保留 1 位小数，时长写成 `mm:ss`；`Δ` 带正负号。

## 本地预览

从项目根目录执行，需要 Python 3：

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory web
```

打开 http://127.0.0.1:4173/ 。必须走 HTTP，`fetch` 才能读到四份 JSON。

## 重新生成媒体

四个原始 MP4 保留在 `resource/`，不进入 Git（其中一个超过 GitHub 单文件限制）。网站使用
`resource/matches/` 内的压缩副本，原始视频不会被覆盖。

准备 FFmpeg（同时提供 `ffprobe`），将原始文件放回 `resource/`，然后从项目根目录运行：

```powershell
python web/tools/prepare_media.py
python -B web/tools/check_site.py
node --check web/app.js
```

生成器复用已存在的网页 MP4；需要重新编码某段录像时，先删除对应的
`resource/matches/<id>.mp4`，再运行生成器。生成器会刷新封面与 `matches.json`；改标题、说明时
同步修改生成器里的记录定义。

网页录像采用 H.264、AAC、`yuv420p` 与 MP4 faststart，优先保证浏览器兼容和快速起播。

## 发布 GitHub Pages

Pages 的构建来源是 **GitHub Actions**，工作流见
[pages.yml](../.github/workflows/pages.yml)：

1. `main` 上的 `web/**` 或工作流文件变化时自动运行，也支持手动触发；
2. 先跑 `check_site.py` 与 `node --check`，再把网页与播放资源复制到 `_site/`（不发布原片与开发工具）；
3. 上传 artifact 并部署到 Pages。

手动触发与查看：

```powershell
git push publish main
gh workflow run pages.yml --repo KKTQawa/RWX-Agent --ref main
gh run list --repo KKTQawa/RWX-Agent --limit 3
```

新增 `resource/` 下的文件类型时，记得同步 `pages.yml` 的拷贝清单，否则线上会 404
（`theme.js`、`micro-results.json`、`CASE*.mp4` 就是这样补进去的）。

## 同步 RWX 源码

本项目基于 RWX 扩展修改，并定期同步上游。`origin` 用于同步原始源码，`myfork` 保持上游跟踪，
个人开发只发布到独立的 `KKTQawa/RWX-Agent`。

以上是维护者工作区的远程命名。首次从本公开仓库克隆时，`origin` 默认指向 RWX-Agent；如需采用
相同约定，先执行（已配置的维护者工作区无需重复）：

```powershell
git remote rename origin publish
git remote add origin https://github.com/yomi2539/RWX
```

之后同步上游并发布：

```powershell
git switch main
git fetch origin
git merge origin/main
git push publish main
```

存在合并冲突时，先在本地解决、检查并提交，再发布；不将个人扩展推送到 `origin` 或 `myfork`。
