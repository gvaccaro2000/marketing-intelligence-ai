# Dice Kingdom marketing analytics (synthetic UA data).
# Source tables live in Redshift schema `marketing`: ua_spend, cohorts, daily_kpis.
# Design notes (fan-out, cohort maturity, Organic): see looker/README.md.

connection: "redshift_marketing"

include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"

week_start_day: monday

# New data lands once per day; rebuild persistent derived tables when ua_spend gets a new date.
datagroup: marketing_daily {
  sql_trigger: SELECT MAX("date") FROM marketing.ua_spend ;;
  max_cache_age: "24 hours"
}

persist_with: marketing_daily

# Cohort quality and ROAS. Grain: install_date x channel x campaign x country x platform.
# Spend is joined from a derived table already summed to cohort grain (no creative_id),
# so each cohort row matches exactly one spend row and nothing is double-counted.
explore: ua_performance {
  label: "UA Performance (cohorts + spend)"
  description: "Install cohorts with retention, revenue, payer conversion and ROAS, joined to paid spend at cohort grain. Use for anything that combines spend with cohort revenue or retention."
  from: cohorts
  view_name: cohorts

  join: spend_cohort_grain {
    type: left_outer
    relationship: one_to_one
    sql_on: ${cohorts.install_raw} = ${spend_cohort_grain.install_raw}
      AND ${cohorts.channel} = ${spend_cohort_grain.channel}
      AND ${cohorts.campaign} = ${spend_cohort_grain.campaign}
      AND ${cohorts.country} = ${spend_cohort_grain.country}
      AND ${cohorts.platform} = ${spend_cohort_grain.platform} ;;
  }
}

# Paid-media delivery down to creative level. Has no cohort revenue or retention.
explore: ua_spend {
  label: "UA Delivery (creative level)"
  description: "Daily paid-media delivery by channel, campaign, country, platform and creative: spend, impressions, clicks, installs, CPI, CTR, IPM. No revenue or retention (cohorts have no creative_id)."
}

# Game-wide daily KPIs by platform. Cannot be split by channel, campaign or country.
explore: daily_kpis {
  label: "Game KPIs (daily)"
  description: "Game-wide DAU, revenue, payers, ARPDAU and daily payer rate by date and platform. All users, paid and organic; not attributable to channels."
}
