# Dice Kingdom knowledge base (synthetic)

A fictional internal knowledge base for the growth team at **Pipfall Games**, the (made-up)
studio behind **Dice Kingdom**. It sits next to `data/marketing.duckdb` and covers the same
period, **2026-06-01 → 2026-08-29**, using the same channels, campaigns, creatives, countries
and platforms. All people, companies' internal tools (e.g. the MMP "Attributa") and
conversations are invented. Ad networks are referred to by the channel names used in the data.

Use it to practise answering questions that need both the data and the "why" behind it:
what the team noticed, what they thought was going on, and what they decided.

## Layout

```
knowledge/
├── slack/
│   ├── users.json            # people and roles
│   ├── ua-team/              # day-to-day buying, pacing, network issues
│   ├── creative/             # briefs, production, creative tests
│   ├── marketing-leads/      # budget approvals and decisions
│   └── data-questions/       # metric questions and analyses
└── confluence/               # wiki pages (Markdown with YAML front matter)
```

### Slack threads (`slack/<channel>/<YYYY-MM-DD>_<slug>.json`)

One file per thread (44 threads):

```json
{
  "id": "ua-team_2026-06-01_summer-flight-live",
  "channel": "#ua-team",
  "author": "Tomasz Wierzbicki",
  "timestamp": "2026-06-01T08:12:00Z",
  "messages": [ { "author": "...", "role": "...", "timestamp": "...", "text": "...", "reactions": [":rocket: 4"] } ],
  "replies":  [ { "author": "...", "role": "...", "timestamp": "...", "text": "..." } ]
}
```

`messages` holds the top-level post, and `replies` holds the thread replies in time order.
All timestamps are UTC. `reactions` is optional. Some threads continue several days after the
first post, and a topic can run across more than one channel.

### Confluence pages (`confluence/*.md`)

Each page starts with front matter:

```yaml
---
title: ...
space: User Acquisition | Analytics | Creative | Marketing Leadership | Product
owner: ...
last_updated: YYYY-MM-DD
status: current | approved | final | draft | deprecated
---
```

Some pages carry extra keys (`supersedes`, `superseded_by`, `approved_by`, `severity`).

| Area | Pages |
|---|---|
| Playbooks & process | UA Playbook, Creative Testing Process, Invalid Traffic Policy, Weekly UA Report Template |
| Definitions | Metric Definitions, D7 ROAS Definition (legacy), Marketing KPI Glossary |
| Channels | Channel Notes for Meta, Google, AppLovin, Unity, TikTok |
| Planning | Q3 2026 UA Budget Plan |
| Measurement & product | Measurement & Attribution, Android Release Log, post-mortem(s) |
| People | Growth & Marketing Team Directory |

## Reading it like a real wiki

The corpus is deliberately messy in the way real ones are:

- Not every page is current. Check `status`, `last_updated` and any banner before trusting a
  page. When two pages disagree, prefer the canonical, most recently updated one and say
  which you used.
- Some pages are drafts or near-copies of other pages, with small differences.
- People in Slack sometimes guess wrong. Read a thread to the end, and look for follow-ups in
  other channels, before quoting a conclusion.
- Slack figures are what people saw at the time. Check them against the database, and follow
  the metric rules in `CLAUDE.md`, before reporting a number.

## Who's who

See `slack/users.json` or the *Growth & Marketing Team Directory* page.
