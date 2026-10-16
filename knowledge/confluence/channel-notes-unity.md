---
title: Channel Notes — Unity
space: User Acquisition
owner: Daniel Esposito
last_updated: 2026-08-26
status: current
---

# Channel Notes — Unity

~10% of paid spend. Cheapest reported CPI of the paid networks, **but see the warning below**.

## Campaigns

| Campaign | Objective | Creatives |
|---|---|---|
| `unity_playable_installs` | Install volume with playable ads | UNT-PLY-01..03 |
| `unity_video_retarget` | Video, lapsed-player retargeting | UNT-VID-01..03 |

## ⚠️ unity_video_retarget — invalid traffic since 2026-07-09

From 2026-07-09 (ramping over ~5 days) the campaign receives a large volume of invalid
clicks and installs on top of its real traffic. Spend is unchanged; reported installs more
than doubled, so CPI looks ~55% cheaper. CTR is ~5× normal and click→install CVR halved.
The extra installs don't retain or pay. Revenue is unchanged.

- Do **not** use this campaign's CPI or installs as a benchmark.
- Sub-publisher blocklist (2026-07-24) did not change the pattern.
- Unity credited part of July as invalid traffic (2026-08-25).
- Campaign to be paused from 2026-09-01, budget moved to `unity_playable_installs`.

Details: *Invalid Traffic Policy*, #ua-team and #data-questions threads from mid-July.

## unity_playable_installs

Clean. CPI ~$1.16, CTR ~1.6%. Playable file size limit 5 MB.
