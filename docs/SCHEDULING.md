# Current public-page follow-up

The live public collector now supports chart/detail/first-player snapshots without app exports. This is separate from the older inbox-only examples below.

Loaded job: `org.hongguo.research.followup`. Due: **November 10, 2026, 8:23 PM America/Los_Angeles** (`2026-11-11T04:23:00Z`). It checks the UTC deadline every five minutes, performs no early network collection, collects one public-page follow-up, exports the data/report and unloads itself. The initial launchd run returned `pending`, exit code 0. No second snapshot is counted yet.

State: `output/research_completion/schedule_24h.json`; configuration: `output/research_completion/org.hongguo.research.followup.plist`; logs: `followup_launchd.log` and `followup_launchd.err` in that directory. Future results: `output/research_completion/followup_24h/`.

```bash
# Inspect loaded job and stored result (project root)
launchctl print gui/501/org.hongguo.research.followup
cat output/research_completion/schedule_24h.json
# Reload after reboot/logout if still pending; plist is project-owned, not installed in Library.
launchctl bootstrap gui/501 /path/to/Hongguo_Research_Crawler/output/research_completion/org.hongguo.research.followup.plist
# Manual deadline-guarded run; before due time this makes no network request.
.venv/bin/python scripts/followup_snapshot.py output/research_completion/schedule_24h.json
# Cancel the pending job
launchctl bootout gui/501/org.hongguo.research.followup
```

The Mac must be running and the user session available near the deadline. Sleep/logout or network failure may delay collection; the report uses actual timestamps and pairs only comparable same-source/scope/precision observations 20–30 hours apart. Failure never creates an observation. An unhandled workflow failure has at most three scheduled attempts. Public preview access still does not provide native danmaku, full comment history, all-episode metrics, or video files.

---

## Earlier documentation

# 约 24 小时重复采集（macOS/Linux）

第一步先**确认实际授权的数据源能生成每集指标和原生弹幕导出文件**，再设置定时器。没有该源，定时运行只能处理已经存在的文件，不能凭空从红果 App 拿到新数据。

```bash
# 项目根目录
bash scripts/daily_pipeline.sh
```

在 Mac/Linux 的 `crontab -e` 设置每日一次（使用你真实的项目路径及 Python 环境）：

```cron
0 9 * * * cd /ABSOLUTE/PATH/Hongguo_Research_Crawler && /ABSOLUTE/PATH/Hongguo_Research_Crawler/.venv/bin/python -m hongguo sync-inbox --inbox data/inbox >> output/import.log 2>&1
10 9 * * * cd /ABSOLUTE/PATH/Hongguo_Research_Crawler && /ABSOLUTE/PATH/Hongguo_Research_Crawler/.venv/bin/python -m hongguo report --out output/reports >> output/report.log 2>&1
15 9 * * * cd /ABSOLUTE/PATH/Hongguo_Research_Crawler && /ABSOLUTE/PATH/Hongguo_Research_Crawler/.venv/bin/python -m hongguo audit --top 10 --out output/audit >> output/audit.log 2>&1
```

**这份 cron 不会自动从红果取得视频/弹幕/私有互动指标。** 它只在授权提供方按约定定期导出并写入 `data/inbox/` 时处理新增数据。要持续每 5 分钟入库本地已到达弹幕导出文件，可用 `sync-inbox --watch --interval 300`，但需要保持本地进程运行。24 小时配对仅比较同一指标、同一集、同一来源、间隔 20–30 小时的数据。若上游没有按时导出，验收仍然失败。
