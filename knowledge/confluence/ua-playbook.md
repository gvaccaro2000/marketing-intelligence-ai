---
title: UA Playbook
space: User Acquisition
owner: Tomasz Wierzbicki
last_updated: 2026-07-02
status: current
---

# UA Playbook

How the Pipfall Games UA team buys installs for **Dice Kingdom**. Read this before you touch a
budget. Network-specific notes live in the *Channel Notes* pages.

## Scope

- Paid channels: Meta, Google, AppLovin, Unity, TikTok. Two campaigns per channel, three
  live creatives per campaign.
- Organic installs are tracked alongside paid but are not bought; they never count toward
  paid metrics (CPI, CTR, IPM, ROAS).
- Markets: US, UK, DE, JP, BR, FR. Platforms: iOS and Android.

## Market roles

| Market | Role | Notes |
|---|---|---|
| US | Core revenue | ~36% of paid spend |
| JP | Premium | Highest retention and payer rate; we accept a higher CPI |
| UK, DE, FR | Core revenue | ~10% of spend each |
| BR | Volume / algorithm seed | ~20% of spend; cheap installs, low monetization. Share is capped, not optimised on ROAS |

## Daily routine

1. 07:00 UTC: pacing sheet refreshes (spend by channel vs plan).
2. Check yesterday's CPI and installs per channel × platform. Use the warehouse, not network UIs
   (time zones differ; the warehouse is UTC).
3. Look for **breaks, not trends**: a CPI move of more than 30% in a day on one
   channel × platform is worth a look. Check clicks and organic for the same platform before
   reacting (see *Measurement & Attribution*).
4. Budget changes: max ±20% per campaign per day. Larger changes go to the Head of UA.

## Weekly routine

- Monday: weekly UA report (see *Weekly UA Report Template*), Mon-Sun vs previous Mon-Sun.
- Tuesday: creative rotation decisions (see *Creative Testing Process*).
- Thursday: budget reallocation proposal, if any, posted in #marketing-leads.

## Decision rules

- **Scale** a campaign only when D7 ROAS on mature cohorts is at or above target *and* cohort
  quality (D1 retention, D7 payer conversion) is stable. A CPI drop alone is never a reason
  to scale. Sudden efficiency jumps get a data check first (see *Invalid Traffic Policy*).
- **Cut** a campaign on ROAS, not on CPI, and only after the cohorts have matured.
- **Don't pause** a campaign because of a reporting gap. If delivery (spend, clicks) is normal
  and installs vanish, suspect measurement first.
- **Retention changes that hit every channel, including Organic, are not UA problems.**
  Escalate to product.

## Guardrails (Q3 2026)

- Blended paid D7 ROAS ≥ 18% (mature D7 cohorts).
- Blended paid D30 ROAS ≥ 42% (mature D30 cohorts).
- Definitions: *Metric Definitions (v3)*. Do not use the deprecated D7 ROAS page.
