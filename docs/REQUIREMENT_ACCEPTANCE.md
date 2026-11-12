# 逐条验收：老师的 10 部红果短剧要求

## 当前事实（必须明确）

**代码完整 ≠ 已取得红果数据。** 本仓库已做的是公开网页元数据解析器、授权导出摄入器、媒体验证、有限浏览器样本观察、数据库、覆盖率和严格验收。

尚没有在真实红果 App 上完成以下任意一项的「平台级全量获取证明」：
1. 真实 **全平台按实际播放量 Top 10**；
2. 这些剧的 **全部完整视频**；
3. 原生 **视频内时间戳 + 完整历史弹幕池 + 更新复采**；
4. 各集完整 **评论/回复** 与 **每集 20–30 小时间隔的所有指定互动指标**。

红果之外的网站自称“官网”，并不等于获得红果运营方正式认可。`hongguoduanju.com/rank/hot-drama` 在数据语义上是**综合热度**，不是实际播放量。不能把这个榜单重命名成真实播放量 Top 10。

## 数据与真正的完成标准

| 老师的要求 | 系统当前能力 | **验收需要的外部证据** | 不足时必须写 |
|---|---|---|---|
| 10 部播放量最高 | `engagement_snapshots` (drama/views)、`select-top-views` + `audit --selection` | 同一观测日期、同一数据源、候选剧集覆盖范围的实际播放量，候选池范围及排序证据 | `NOT_VERIFIED`; 不能用热度/点赞替代 |
| 剧目目录（含全部分集） | `dramas`、`episodes`、公开 SSR 解析、授权 CSV 导入 | 可追溯剧目 ID、完整集号 1..N、官方/原始页面链接、完结状态、AI 类别 | 缺多少集写清楚；无 ID 不生成虚构 ID |
| 全部完整视频 | 已授权视频直接下载或导入，ffprobe 时长、SHA-256、是否全片声明，媒体清单 | 合法使用权、原始剧集完整时长/独立首尾检查；文件可解码、非试看/裁剪 | `unverified`；没有视频不要写已采集 |
| 字幕（如可得） | 独立 SRT/VTT 导入 + 关联分集 | 授权字幕或清楚的不可用证明；烧录字幕记录到人工审核 | `missing/unavailable`，区分两者 |
| 原生实时弹幕 | 导入有 `playback_time_ms` 的授权数据；网页 DOM 可见弹幕采样；按消息 ID 去重 | 分集、原文、**平台原生**播放偏移、消息 ID/发送时间（如提供）、采集时间、历史池覆盖/分页完成证据及 24h 复采 | 仅可见样本为 `sampled_visible`；估测时间为 `estimated_observation`；**评论不算弹幕** |
| 各集指标 | `engagement_snapshots` 的 `scope=episode` + 时间戳、来源、精度，20–30h 匹配 | 每集 likes/favorites/comments/rating/heat/rank；views/shares 可得时也采；每项两次，同来源 | 缺哪一集、哪个指标/快照分别报告 |
| 剧目指标 | 相同快照库，`scope=drama` | 明确整剧/分集级别；排名和播放量定义不能互换 | 非公开/无精确计数时如实标注 |
| 评论、剧评、回复 | `comments` 的 `comment_id`,`parent_id`, 时间、点赞、采集来源 | 逐集原始文本和回复关系，覆盖数、实际页面/授权数据源证明 | 第三方仅给 replyCount **不等于** 已保存回复正文 |
| AI/真人、真人相似度、配音/字幕 | `drama_reviews` + 视频采帧，人工 1–5 分评估 | 检查范围、评审人、是否 AI、语音/字幕语言、真人相似度定义 | `unknown`；不以类别标签冒充人工判断 |
| 可复跑与失效处理 | SQLite 去重、失败记录、`sync-inbox`、`report`、`audit` | 重复运行没有重复计数；下游报表对缺失/失败如实说明 | 记录失败原因、权限、网址变动、限流 |
| 扩容到 100 / 1000 | `scale_estimate.json` 的容量/传输/ASR/OCR 假设 | 用真实 pilot 的平均集数、单集大小、下载速率与失败率重新估算 | 没有实测时只报 **assumptions** |

## 新增严格检查命令

所有安装和基础使用请见仓库主 README。下例只说明验收相关命令。

```bash
# 从已获许可的来源导入，先剧目、再分集，后续增量导入
python -m hongguo import dramas data/authorized/dramas.csv --source permitted_provider
python -m hongguo import episodes data/authorized/episodes.csv --source permitted_provider
python -m hongguo import danmaku data/authorized/danmaku.csv --source permitted_provider
python -m hongguo import comments data/authorized/comments.csv --source permitted_provider
python -m hongguo import engagement data/authorized/metrics_first.csv --source permitted_provider
# 24h 后由你/允许的服务端再次取得并保存源文件
python -m hongguo import engagement data/authorized/metrics_second.csv --source permitted_provider
```

数据范围与可追溯性证明，填写 `examples/source_receipts_TEMPLATE.csv`，每集每个数据集可记录多次，**只在有完整来源证明时使用 `full_source_attested`**：

```bash
python -m hongguo import receipts data/authorized/source_receipts.csv --source permitted_provider
```

先用确实来自「实际播放量」的整剧指标选择 Top 10，再**人工核对候选池**、填写 `examples/top10_source_attestation_TEMPLATE.json`：

```bash
python -m hongguo select-top-views --top 10
python -m hongguo audit --selection data/authorized/top10_source_attestation.json --out output/audit
```

其中 `covers_entire_target_population` 是研究者的**可检查的来源声明**，软件无法仅凭 JSON 验证平台是否真的提供了所有短剧。审计结果即使显示 `SOURCE_ATTESTED_COMPLETE_NOT_INDEPENDENTLY_VERIFIED`，也不是平台对完整性的认证。

结果文件：`acceptance.json`（逐集机器可读检查项）、`episode_acceptance.csv`（逐集表）、`acceptance.md`（给老师的缺失报告）。任何缺口都保留 `INCOMPLETE`，避免虚假完成。

## 持续接收新增数据

把**已通过允许的提供方获取**的 CSV/JSON/JSONL 按类型放进 `data/inbox/dramas/`, `episodes/`, `danmaku/`, `comments/`, `engagement/`, `reviews/`, `receipts/`，先用临时扩展名写入，完整后再改名为 `.csv/.json/.jsonl`。

```bash
python -m hongguo sync-inbox --inbox data/inbox
# 如果需要长期监听文件夹（进程必须一直运行）
python -m hongguo sync-inbox --inbox data/inbox --watch --interval 300
```

`sync-inbox` 是**本地授权导出文件的摄入器**，不是红果实时弹幕接口。它按内容哈希记录已处理文件，去重导入。没有合法的上游定期导出，不能自行持续获取新弹幕。

## 还必须接通的外部来源

1. **排名：** 获得真实剧目级播放量，以及覆盖候选池的来源证明。公开热度榜不等价。
2. **视频：** 获得完整视频及研究下载/存储授权。仅有可播放预览、短期 CDN URL 不等于可合法稳定批量归档。
3. **弹幕：** 获得明确的、平台原生带播放偏移的授权数据接口/导出；核实历史池、分页/游标与更新机制。第三方评论 Actor 提供的 `offsetTimeMs` 字段只有在语义核实后才可用于弹幕分析。
4. **互动指标：** 核对红果是否真的展示每集的全部 requested metrics。缺失的单集评分/榜单位次不能从整剧数值推算。
5. **评论回复：** 选择同时提供线程正文的来源，不仅仅有“reply count”。

**有来源 + 有权限 + 真正返回字段 + 本地复核** 才能说“确保获取”；任何环节缺失，必须如实告知老师并将该项列为瓶颈。
