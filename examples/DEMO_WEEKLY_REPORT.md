# Micro-drama pilot — automated collection report
Generated (UTC): 2026-11-09T11:29:20+00:00

## Collected items (actual database records)
| Measure | Count |
|---|---:|
| dramas | 2 |
| episodes | 3 |
| danmaku | 2 |
| comments | 2 |
| ranking_snapshots | 2 |
| engagement_snapshots | 5 |
| assets | 0 |
| drama_reviews | 0 |
| videos_verified_full | 0 |
| videos_valid | 0 |
| danmaku_native_timestamps | 2 |

## Per-drama coverage
| Drama | IDs / expected | Valid videos | Verified full | Native timed danmaku | Comments |
|---|---:|---:|---:|---:|---:|
| 演示短剧甲（虚构） | 2/2 | 0 | 0 | 2 | 2 |
| 演示短剧乙（虚构） | 1/1 | 0 | 0 | 0 | 0 |

## 20–30 hour engagement changes
- DEMO_DRAMA_001 / DEMO_EP_001 / likes: 100.0 → 120.0 (Δ +20, 24.0h)

**DEMO / SYNTHETIC DATA PRESENT — counts are not real collected Hongguo observations.**

## 20–30 hour ranking changes
No rank pairs observed approximately 24 hours apart.

## Data quality / missing data
- DEMO_DRAMA_001: 0/2 listed episodes have verified-full media
- DEMO_DRAMA_002: 0/1 listed episodes have verified-full media
- DEMO_DRAMA_002: no authentic timed danmaku collected

## Scaling projections (assumption-based until pilot videos exist)
| Dramas | Episodes | Storage (GB) | Ideal network transfer (hours) | ASR compute (hours)* | OCR compute (hours)* |
|---:|---:|---:|---:|---:|---:|
| 10 | 15 | 0.45 | 0.05 | 0.19 | 0.38 |
| 100 | 150 | 4.5 | 0.5 | 1.88 | 3.75 |
| 1000 | 1500 | 45.0 | 5.0 | 18.75 | 37.5 |

*ASR/OCR speeds are hypothetical engineering assumptions, not benchmarked performance.*

## Critical interpretation rules
- Ranking **heat** is a composite score, not confirmed playback count.
- Text comments **must not** be counted as playback-timed danmaku.
- Browser-visible danmaku is sampled/partial, not the complete historical pool.
- Only rights-confirmed videos with duration checks can be technically labeled verified_full.
- Estimates do not include rights/availability bottlenecks.
