# 红果短剧研究数据采集系统 (Hongguo Research Crawler)

## Current research run (2026-11-09 Pacific)

See [verified collection status](docs/RESEARCH_COMPLETION_STATUS.md) and the [three-repository review](docs/REPOSITORY_COMPARISON.md).
Actual results: 10 dramas / 2,826 episode IDs reconciled; 240 comment/review previews; 22 episode metric observations on 10 first episodes; 22 existing visible overlays / 137 sightings. **Native danmaku: 0. Verified full Hongguo videos: 0.** These two priority requirements remain blocked by the absence of a demonstrated authorized source. Original SQLite records are preserved.

Generate the current evidence report with `python -m hongguo research-report`; open `output/research_completion/report/report.html`. The separate `research-snapshot` collector, native raw-field/pagination fixes and optional `media-import --resume-transfers` are documented in the linked status file. A public-only 24-hour follow-up is scheduled; it has not yet been collected.



## GitHub source-code snapshot (November 2026)

This repository contains the **source code, tests, public documentation, and synthetic demo fixtures** from the research crawler. Uploaded archives intentionally exclude: local SQLite databases and backups, runtime/browser output, screenshots and OCR captures, virtual environments, downloaded third-party repositories, cached dependencies, device-identifying runtime state, and credentials. These are **not** required for inspecting the code and should not be made public.

**Scope of verified data:** 10 hot-ranking *candidate* dramas and 2,826 episode IDs were indexed; these are not a proven top-10 by actual play counts. Native full-history danmaku and full episode videos were not verified or exported. The separate QuickTime experiment processed 178 existing image frames; 38 scrolling events are estimates, and 100% sample text accuracy applies only to 20 manually reviewed examples (excluding punctuation/emoji), **not** full recall.

**QuickTime OCR source:** `experiments/quicktime_ocr/` includes Apple Vision OCR (macOS/iPhone QuickTime capture), frame tracking, and the offline `reprocess.py`/tests. The captured video frames and test run evidence remain local; a fresh evaluation requires your own authorized test recording.

**Optional offline native API feasibility:** `experiments/hgtv_offline/` holds original bridge/build investigation code but deliberately excludes downloaded upstream vendor signing sources and binaries. Its dependency build will not run without separately obtained, properly licensed dependencies; please see the linked feasibility docs. No native danmaku access success is claimed.

**Security and access:** Only collect or import data you are authorized to access; the crawler has conservative public-page collection behavior. Never commit cookies, API tokens, session credentials, signed traffic, or personal information.

## Earlier collection history

> **最新可见弹幕实测：** 已按用户要求增加独立的屏幕可见覆盖层采集模式，先验证单集，再采样原有 10 部剧各第 1 集。实际入库 **22 条可见覆盖层记录、137 次带观测时间的目击记录**；22 条均匹配到普通评论的原始发布时间。页面未提供原生消息 ID 或播放偏移，这两项保留 NULL。SQLite 原表全部保留；60 项测试通过。详见 [可见覆盖层来源、字段与复跑说明](docs/VISIBLE_OVERLAY_COLLECTION.md)。下文 0 条的历史结论指原生弹幕接口，不能理解为网页没有滚动文字。

**研究用途的数据工程工具包**，提供：公开网页榜单/分集目录采集、SQLite 增量存储、授权视频文件验证、平台原生时间戳弹幕导入、可见弹幕采样、普通评论/回复、分剧/分集互动指标及 24 小时快照、人工 AI/真人审核、质量/覆盖率报告，以及 10→100→1000 扩容预估。

> **2026-11-09 实测更新：** 已完成真实公开页面检查及单集原生弹幕接口探测；原生接口返回 HTTP 200 / 平台错误 `110001`，未返回弹幕。**真实弹幕、视频、逐集互动指标本次新增均为 0，成功的在线弹幕 POC 仍受访问限制。** 已实现严格原生响应解析、增量去重/更新、证据保存、视频完整解码与独立时长验证、逐集指标追踪。详见 [实测结果、阻碍及复现步骤](docs/NATIVE_COLLECTION_STATUS.md)。已有 SQLite 数据已备份且全部保留；其中旧 demo 数据仍保留，报告区分非 demo 统计。

> **重启后浏览器核验：** 用户已登录 Chrome，但当前连接报 `Browser is not available: chrome`，未能使用该登录会话。在独立的内置浏览器实际播放第一集后，确认页面的滚动文字来自普通 `reviews`，由前端生成 `dm-init-*` 编号和显示时间，不能作为原生弹幕入库。证据见 `output/browser_followup/`。已加入拒收规则、有限瞬时错误重试和 `--resume` 断点续跑；52 项本地测试通过，仍未获得真实原生弹幕，未扩展到 10 部剧。

## 最新要求：严格逐集验收与增量导入

如果研究目标是**真实播放量最高的 10 部红果短剧**，尤其需要完整分集视频、平台原生实时弹幕、约 24 小时复采、逐集指标以及评论回复，优先阅读 **`docs/REQUIREMENT_ACCEPTANCE.md`**。内含字段验收矩阵、10→100→1000 的资源依赖、可用/不可用判据和下一步必须接通的数据来源。**当前还不能宣称所有数据已经获取。**

新增命令：

```bash
python -m hongguo sync-inbox --inbox data/inbox       # 单次导入授权来源的新增 CSV/JSON
python -m hongguo sync-inbox --inbox data/inbox --watch --interval 300 # 本地导出文件持续入库，进程需保持运行
python -m hongguo import receipts real_receipts.csv --source permitted_provider
python -m hongguo audit --top 10 --out output/audit    # 未提供来源证明时仍标 INCOMPLETE
# 如已拿到真实全候选池播放量排名证明：
python -m hongguo audit --selection real_selection_attestation.json --out output/audit
```

报告中的 `SOURCE_ATTESTED_COMPLETE_NOT_INDEPENDENTLY_VERIFIED` 意为**导出方/研究者有可检查来源证据并声称覆盖完整**，不表示已独立验证红果全站数据。数据是否在平台可用、获准导出和是否完整仍必须实际核查。

另外：`hongguoduanju.com` 可以作为第三方公开榜单页面的数据样本，但**尚未验证它是红果运营方的官方网站**，且它的榜单是综合热度；不能将其标记为官方真实播放量 Top 10。

## Code validation for this public source snapshot

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s experiments/quicktime_ocr -p 'test_*.py' -v
```

On the sanitized source snapshot, both suites passed locally (82 crawler/data tests and 11 OCR tests, respectively). These do not contact the Hongguo native API or establish completeness of collected data. macOS Apple Vision/QuickTime capture is only available with the corresponding local runtime and permission.

## A. 快速启动（macOS / Linux / Windows）

需要 Python 3.10+。在项目根目录：

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

**先运行无网络模拟数据，检查所有输出**：

```bash
python -m hongguo --db output/DEMO_ONLY.sqlite demo --fixtures-dir examples --out output/DEMO_REPORT
```

包含 `DEMO_DRAMA_*` 的全部数据均为虚构样本，勿在研究汇报中当成真实短剧。

## B. 真实榜单与目录

在检查网页的使用条款、采集权限与 robots.txt 后：

```bash
python -m hongguo crawl --top 10 --rank hot-drama --delay 2
python -m hongguo export --out output/csv
python -m hongguo report --out output/reports
```

也可指定 `--rank hot-ai-drama`、`hot-real-drama`、`hot-comic-drama`。`crawl` 默认只采公开 `hongguoduanju.com` HTML（SSR `_ROUTER_DATA`），不读取 App 私有接口或绕过签名。公开网页结构可能改变。工具在 `robots.txt` 无法确认时停止，收到 429 会退避，默认按顺序请求、相隔至少 2 秒。

**筛选规则警告：** `hot-drama` 是**综合热度榜**，不是严格的「播放量最高」榜。若老师坚持真实播放量 Top 10，应先获得有来源的真实 drama-level view 数据后使用：

```bash
python -m hongguo import engagement examples/episode_metrics_TEMPLATE.csv --source authorized_export
python -m hongguo select-top-views --top 10 --out output/top10_by_actual_views.csv
```

上面的 TEMPLATE 是字段示例，须先用**实际授权的数据**替换 `REAL_DRAMA_ID` 和虚构 URL。该命令如实际播放量不足 10 部会明确告警，不会用 heat 冒充 views。

### 源站页面解析失败如何处理

在 Chrome 中保存榜单 HTML（不是截图），然后：

```bash
python -m hongguo crawl --offline-rank-html saved_rank.html --top 10 --skip-details
```

离线模式**不会**偷偷联网。欲补详情，保存每部剧的 HTML 为 `details/<drama_id>.html`，加 `--details-dir details`。出现 `seriesDetail missing` 时应检查实际公开 HTML，不要猜造 episode ID。

## C. 完整视频与字幕（仅已有采集权/导出权的数据）

本程序支持导入通过平台许可、研究授权或其他合法来源获得的完整视频，也可以选择性下载许可范围内的**直接 HTTPS 非加密视频文件**。不会获取/解密 DRM、读取私有 App 视频密钥或绕过付费和登录。

1. 先保证 `dramas`、`episodes` 在数据库中。
2. 打开 `examples/media_manifest_TEMPLATE.csv`，每集一行填写真实 `drama_id`,`episode_id`,授权文件 `local_path` 或 `direct_url`, `rights_confirmed=true`, `access_basis`（授权依据）, `is_full_episode`, `expected_duration_seconds`, `subtitle_path`（可选）。
3. 安装 FFmpeg（需要 `ffprobe`），然后：

```bash
python -m hongguo media-import my_media_manifest.csv --media-root data/media
```

如果有**明确许可**的直接 HTTPS `.mp4/.mov/.mkv/.webm` 文件：

```bash
python -m hongguo media-import my_media_manifest.csv \
  --media-root data/media --download-authorized --allowed-host authorized-video.example.org
```

视频检查包括：文件真实可解码为视频、FFprobe 实际时长、SHA-256 checksum、大小、预期时长误差、来源权限声明。只有完整解码成功、`is_full_episode=true` 且时长与独立来源的预期相符才标记 `verified_full`；这只是**技术验证**，不能替代人工确认视频没有缺段或片头预览。视频和个人敏感信息不要上传公开 GitHub。

人工审核视频帧：

```bash
python -m hongguo frames data/media/DRAMA_ID/EPISODE_ID.mp4 --out output/frames/DRAMA_ID --count 4
```

如果只有授权字幕、暂时没有视频，也可以独立导入：

```bash
python -m hongguo subtitle-import my_subtitles_manifest.csv --out data/subtitles
```

模板见 `examples/subtitles_manifest_TEMPLATE.csv`。

## D. 真实弹幕 vs 普通评论

**当前可用的独立模式：** `hongguo/visible_overlay_snapshot.js` 通过已连接浏览器的只读 DOM API 采集实际显示的滚动文字，并匹配页面公开内嵌评论的发布时间。以 `*.capture.json` 保存后，运行 `.venv/bin/python -m hongguo visible-overlays output/visible_overlays` 导入独立表和导出 CSV。该 CLI 是证据导入器，不会自行接管 Chrome；浏览器采样仍需要连接的浏览器控制器。全部结果标为 `sampled_visible`，观测播放位置与平台原生偏移分列。详见 [实现与限制](docs/VISIBLE_OVERLAY_COLLECTION.md)。

**需要平台授权数据渠道才能声称获得完整历史弹幕池和原生时间戳。** 两条可用路径：

**1. 授权平台导出（首选）**：下载平台提供的 CSV/JSONL 后统一字段：

```bash
python -m hongguo import danmaku my_authorized_danmaku.csv --source official_authorized_export
python -m hongguo import comments my_authorized_comments.csv --source official_authorized_export
```

弹幕最少必须有 `drama_id, episode_id, text`，强烈要求 `playback_time_ms`（出现于视频的毫秒偏移），`message_id`, `posted_at`（若平台提供）。仅当秒数是**平台提供的原生时间**才写 `timing_method=platform_native`；通过播放观察估出的时间标为 `estimated_observation`。通过 `message_id` 或组合键去重。评论可保留 `parent_id` 建立回复关系，但永远不记为弹幕。

**2. 网页可见弹幕采样（可选）**：网页确实在 DOM 中渲染弹幕、你具备采集权限时，可用 Playwright 观察播放期间**当前可见**的弹幕：

```bash
pip install -r requirements-browser.txt
python -m playwright install chromium
python -m hongguo browser-danmaku \
  --url 'https://ALLOWED_SITE/player/VIDEO' --allowed-host ALLOWED_SITE \
  --drama-id REAL_DRAMA_ID --episode-id REAL_EPISODE_ID \
  --selector '.YOUR_REAL_DANMAKU_MESSAGE_CSS' --video-selector video \
  --seconds 120
```

注意：上面的 CSS 和网址是**占位示例**，需要按你拥有授权的真实网页检查 DOM。浏览器无法读取画在 Canvas 上的弹幕，此功能只收当前可见 DOM 文本，**不能声称是全部实时弹幕**。没有平台原生时间属性时，保存的秒数只是观测估计，不等于平台真实时间。程序会检查公开页面 robots.txt；并且不会调用隐藏 App API 或拦截私有网络通信。

普通评论也可以使用可见 DOM 的有限滚动采样（字段若未在网页 DOM 提供会留空）：

```bash
python -m hongguo browser-comments --url 'https://ALLOWED_SITE/page' \
  --allowed-host ALLOWED_SITE --drama-id REAL_DRAMA_ID \
  --selector '.YOUR_REAL_COMMENT_CSS' --scrolls 5
```

需要先检验你有权访问的真实网页 CSS selector；不能把这个命令说成已支持红果 App 评论全量采集。

若页面需要你自行授权登录，可传 `--profile-dir` 使用本地浏览器配置；绝不可把该目录上传 GitHub。

## E. 互动指标与 24 小时快照

指标使用 `scope=drama` 或 `scope=episode`，`metric` 为 `views, likes, favorites, comments, shares, rating, heat, rank` 等；请注明 `precision=exact/rounded_display` 和 `source`。热度与真实播放量是**不同指标**。

```bash
python -m hongguo import engagement my_2026_11_09.csv --source licensed_source
# 在约 24 小时后同一来源重复采集/导入
python -m hongguo import engagement my_2026_11_10.csv --source licensed_source
python -m hongguo report
```

系统只比较**同一剧/集、同一指标、同一来源、观测时间相差 20–30 小时**的观测对。公开榜单每次 `crawl` 都保存 `ranking_snapshots`，支持排名与热度变化的比较。要定时运行请自行配置 macOS launchd、cron 或工作站调度器；本程序本身不会在退出后持续采集。

## F. AI 分类、真人相似度、配音/字幕检查

将人工审核表填写为 CSV，并导入：

```bash
python -m hongguo import reviews my_manual_reviews.csv --source human_review
```

字段参考 `examples/reviews_TEMPLATE.csv`：AI / 真人 / mixed，真人相似度 1–5（**主观人工评级**），voice_language，voice_type，subtitle_language，是否烧录字幕、审核帧数、置信度和 note。不要把 `hot-ai-drama` 标签当成真实图像的人工审核结论。

## G. 导出和最终汇报

```bash
python -m hongguo export --out output/csv
python -m hongguo report --out output/reports \
 --assumed-episodes 80 --assumed-mb 30 --download-mbps 20
```

生成：

```
data/hongguo.sqlite         SQLite 真正的增量数据库
output/csv/dramas.csv
output/csv/episodes.csv
output/csv/danmaku.csv
output/csv/comments.csv
output/csv/engagement_snapshots.csv
output/csv/ranking_snapshots.csv
output/csv/drama_reviews.csv
output/csv/assets.csv
output/csv/collection_events.csv
output/reports/coverage_report.json
output/reports/scale_estimate.json
output/reports/weekly_report.md
```

`weekly_report.md` 自动报告每部剧 episode ID 覆盖率、有效/完整视频、是否具有**平台原生时间**的弹幕、评论量、24h 增量、失败记录和 10/100/1000 的存储及计算估算。扩容成本为**带明示假设的粗估**，没有视频样本时不能拿来当已测量结果。

## H. 本周验收 checklist

- [ ] 有研究授权与可追溯的数据来源；确认官方/公开网页与 App 的适用规则。
- [ ] 10 个真实剧名、来源 URL、ID、排名日期、题材、AI 分类、完结状态、总集数。
- [ ] 分集 ID 表与真实集数对照；每一条缺失集数均标记。
- [ ] 授权的完整视频（每集）与时长/校验值；不可获取的逐集保留失败原因。
- [ ] 真正的带播放偏移时间的弹幕；缺失、抽样、推算时间不得标完整。
- [ ] 评论/剧评与回复、发布时间、点赞数，记录抽样范围。
- [ ] drama-level 与 episode-level 的指标严格分开；首次和约 24h 后各采一次。
- [ ] 生成 SQLite、CSV、周报及失败日志，能够复跑而不会重复写入弹幕/评论。
- [ ] 测量实际单集体积和采集速度后，重新估算 10→100→1000。

## 安全与研究伦理

尊重平台使用条款、`robots.txt`、下载与文本保存权限，确认研究团队是否需要伦理/隐私审查。项目不会解密视频 DRM、伪造 App 签名、绕过反爬与访问控制，也不保存登录凭证到代码仓库。弹幕/评论可能包含个人信息，按最小必要原则存储、限制访问并遵循研究机构的保留和删除要求。

公共页面入口：<https://hongguoduanju.com/rank/hot-drama>。该入口的榜单定义是综合热度，**不是 verified play count**。
