# RWX-Agent 项目网站

介绍项目能力并播放四场实机对局的静态网站，外加一页评测结果；无前端依赖或构建步骤。

- 网站：https://kktqawa.github.io/RWX-Agent/
- 评测结果：https://kktqawa.github.io/RWX-Agent/results.html
- 本项目源码：https://github.com/KKTQawa/RWX-Agent
- RWX 上游：https://github.com/yomi2539/RWX

## 本地预览

从项目根目录执行，需要 Python 3：

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory web
```

打开 http://127.0.0.1:4173/ 。使用 HTTP 服务预览，以便 JavaScript 读取录像清单与评测数据。

## 修改页面

| 文件 | 内容 |
| --- | --- |
| `index.html` | 首页：评测目录（五个科目卡）、进度追踪演示、系统能力、实机录像、三条结论、快速开始 |
| `results.html` | 评测观察页：完整对局总表（14 列，`total-v2.1` + 四类 Stage3 v3 实扣 / 上限 / 事件数 + 与 v2 的 Δ，行内可展开逐项公式、v2 对照与材料）、当前扣分细则（只含 Stage1-v2 与 Stage3-v2.1）、四个 Micro CASE 的结果表 + 逐项扣分矩阵、口径与「现有结论」 |
| `styles.css` | claymorphism 设计系统：一套 token 同时定义亮 / 暗两套配色（`:root` 与 `[data-theme="dark"]`），另有桌面、平板、手机布局与减少动画适配 |
| `theme.js` | 主题开关：在首屏绘制前把 `data-theme` 写到 `<html>`，记住选择并同步按钮文案；两页共用 |
| `app.js` | 首页录像切换、平台切换、复制命令、手机导航；并从两份 JSON 填充目录卡、进度条与结论卡的数字 |
| `results.js` | 读取 `resource/results.json`、`resource/scoring.json` 与 `resource/micro-results.json`，渲染总表、搜索 / 胜负筛选 / 六种排序、展开行扣分明细、当前规则表与 CASE 逐项扣分矩阵；扣分列名直接取自评分账本 |
| `resource/matches.json` | 四场录像的名称、说明、时长及 SHA-256 |
| `resource/results.json` | schema 3：`matches`（每局带 `v21` 块：total-v2.1、四项扣分、v2 对照与 Δ）、`overview21`（v2.1 统计）、`standard21`（v2.1 公式、权重、上限与标定值）、`standard`/`v1`（v2 与冻结的 v1） |
| `resource/micro-results.json` | 四个固定 CASE 的当前规则（`items`：上限 + 公式）、环境说明与逐局记录；每条记录带 `items` 的 raw / cap / points，页面据此渲染扣分矩阵 |
| `resource/scoring.json` | 只含当前计分的两组：Stage1-v2 与 Stage3-v2.1 的扣分项、上限、公式、说明与 caveat |
| `resource/cases/` | 四个微操 CASE 的固定 task + seed 真实窗口截图（WebP） |
| `resource/matches/` | 已提交的 H.264/AAC 网页录像，完整时长、1080p/60fps |
| `resource/posters/` | 从原录像提取的 WebP 封面 |

本页没有接入游戏实例或云端模型 API。页面中的命令用于在访问者本机启动游戏；录像是真实录制的对局，不是在线游戏画面。

### 主题

两页共用一套 token：`:root` 是亮色，`[data-theme="dark"]` 是暗色。`theme.js` 在首屏绘制前把 `data-theme` 写到 `<html>`（先读 `localStorage.rwx-theme`，没有就跟随系统 `prefers-color-scheme`），页面右上角的按钮只切换这个属性并回写存储。新增颜色请加 token，不要在组件里写死色值，否则另一半主题会失配。

### 数据不写占位符

页面上不出现 `—`：任何数字要么来自评分产物，要么写成一句明确的说明（`未记录` / `材料只记录了评分窗口`）。例如对局时长第二行在没有 `meta.timing.gameSeconds` 时显示证据来源（`实时遥测` / `忠实回放重演`），而不是横杠。新增字段时请沿用这个约定。

## 更新评测结果

评测结果来自仓库的评分产物（`evaluate/output/<对局>/evaluation_v2.json`、`score_v2.json`、`stage_3/score.json`，都不纳入版本库）。更新流程：

1. 按 `evaluate/README.md` 跑完 v2 与 v2.1 评分：v2 出 `_v2-summary.json`，v2.1 出 `_v21-summary.json`（`stage3-score-v2.1-v3`）。页面把 v2.1 当当前口径、v2 当对照；`results.json` 里的 `v1` 块是冻结快照，只为校验保留。
2. 跑 `node evaluate/tools/build_web_results_v2.js`：它读 `_v2-summary.json`、`_v21-summary.json` 与各局 `meta.json`，写 `resource/results.json`。每局的 `v21` 块由 `_v21-summary.json` 的同一 `relativePath` 行合并而来，`total-v2.1` / `stage3-v2.1` / `Δ` 的一致性由 `check_site.py` 复算。模型、工具、推理强度以对局目录 `meta.json` 为准（`evaluate/tools/match_materials.js` 生成并维护），多 Agent 局按 `pairs` 一对一列出。
3. 归档语料缺结构化 `meta.json` 的，在 `build_web_results_v2.js` 顶部的 `ARCHIVE` 表补日期与参与模型；材料不足或重放分叉的局由脚本写进 `ignored`，页面不展示这些局，也不要手工补分。
4. 规则表由 `resource/scoring.json` 提供：`node web/tools/build_scoring_v2.js` 从 `evaluate/config.json` 重新生成 **只有当前计分的两组**——Stage1-v2（3 个特征组 + 活跃度闸门）与 Stage3-v2.1（4 项）。已退役的 v1 / v2 规则不再出现在页面上；v2 只作为总表里的对照列。评测页的四个扣分列标题直接读取这里，改规则后无需再改 HTML。
5. CASE 表由 `python web/tools/build_micro_results.py` 生成：它扫描 `evaluate/output/micro/<CASE>/<run>/meta.json`、`result.json` 与 `eval/metrics.json`，逐局写出模型 id、工具（Pi / DSH）、时长，以及每一项的 raw / cap / points；规则表（上限与公式）由 `evaluate/micro/<CASE>/config.json` 渲染，因此改了 cap 或曲线后重跑脚本即可，不需要再手写说明。四局 DSH 的材料在仓库外，脚本顶部 `EXTERNAL` 表记录其 run id、分数与逐项数值，来源是 `evaluate/output/micro/_review-20261112-dsh-four-cases.md`。
6. 运行 `python web/tools/check_site.py`：校验页面链接、录像校验和、`total-v2.1` / `total-v2` / `total-v1` 三套加权、v2.1 四项上限与 Δ、CASE 行的模型与工具标注、以及「每条记录的逐项 points 之和 = 记录分数」「记录里的 cap 与规则表一致」。规则表和运行产物一旦对不上，校验会直接失败。

`check_site.py` 不读取 `evaluate/`（该目录不进版本库），因此分数一致性以 `results.json` 内部为准。

## 重新生成媒体

四个原始 MP4 保留在 `resource/`，不进入 Git；其中一个超过 GitHub 单文件限制。网站使用 `resource/matches/` 内的压缩副本，原始视频不被覆盖。

准备 FFmpeg（同时提供 `ffprobe`），将原始文件放回 `resource/`，然后从项目根目录运行：

```powershell
python web/tools/prepare_media.py
python web/tools/check_site.py
node --check web/app.js
```

生成器复用已存在的网页 MP4；需要重新编码某段录像时，先删除对应的 `resource/matches/<id>.mp4`，再运行生成器。生成器会刷新封面和清单。更改标题、说明时同步修改生成器内的记录定义与清单。

网页录像采用 H.264、AAC、`yuv420p` 和 MP4 faststart，优先保证浏览器兼容和快速起播。校验器检查本地链接、锚点、视频哈希、四段录像的完整性及站点体积。

## 发布 GitHub Pages

仓库 Pages 的构建来源使用 **GitHub Actions**。工作流见 [pages.yml](../.github/workflows/pages.yml)：

1. `main` 上的 `web/**` 或 Pages 工作流更新时自动运行，也支持手动触发。
2. 校验资源后，仅复制网页与播放资源至 `_site/`，不发布原片或开发工具。
3. 上传 Pages artifact，再部署至 GitHub Pages。

本地已配置发布远程时，可执行：

```powershell
git push publish main
gh workflow run pages.yml --repo KKTQawa/RWX-Agent --ref main
```

没有页面更新时不必手动触发；前一次 Pages 工作流失败时，可查看 Actions 日志后重跑。

## 同步 RWX 源码

本项目基于 RWX 扩展修改，并定期同步上游。`origin` 用于同步原始源码，`myfork` 保持上游跟踪，个人开发仅发布到独立的 `KKTQawa/RWX-Agent`：

以上是维护者工作区的远程命名。首次从本公开仓库克隆时，`origin` 默认指向 RWX-Agent；如需采用相同约定，先执行以下配置（已配置的维护者工作区无需重复执行）：

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
