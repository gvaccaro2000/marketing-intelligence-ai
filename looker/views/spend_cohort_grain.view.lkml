# ua_spend summed to cohort grain: install_date x channel x campaign x country x platform.
# ua_spend has one row per creative (3 per campaign). Joining it straight to cohorts would repeat
# every cohort row 3 times and triple revenue, retention and installs. Summing away creative_id
# first makes this table match cohorts row for row, so the join is one_to_one.
# Organic rows are kept (spend 0) so every cohort row finds its match and installs reconcile.

view: spend_cohort_grain {
  derived_table: {
    sql:
      SELECT
        "date"           AS install_date,
        channel,
        campaign,
        country,
        platform,
        SUM(spend)       AS spend,
        SUM(impressions) AS impressions,
        SUM(clicks)      AS clicks,
        SUM(installs)    AS installs
      FROM marketing.ua_spend
      GROUP BY 1, 2, 3, 4, 5 ;;
    datagroup_trigger: marketing_daily
    distribution_style: all
    sortkeys: ["install_date"]
  }

  # ---- Keys ----------------------------------------------------------------------------------

  dimension: pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CAST(${TABLE}.install_date AS VARCHAR) || '|' || ${TABLE}.channel || '|' || ${TABLE}.campaign
      || '|' || ${TABLE}.country || '|' || ${TABLE}.platform ;;
  }

  # Join keys. Hidden because the same fields are exposed from cohorts.
  dimension_group: install {
    hidden: yes
    type: time
    datatype: date
    convert_tz: no
    timeframes: [raw, date, week]
    sql: ${TABLE}.install_date ;;
  }

  dimension: channel {
    hidden: yes
    type: string
    sql: ${TABLE}.channel ;;
  }

  dimension: campaign {
    hidden: yes
    type: string
    sql: ${TABLE}.campaign ;;
  }

  dimension: country {
    hidden: yes
    type: string
    sql: ${TABLE}.country ;;
  }

  dimension: platform {
    hidden: yes
    type: string
    sql: ${TABLE}.platform ;;
  }

  dimension: is_paid {
    hidden: yes
    type: yesno
    sql: ${TABLE}.channel <> 'Organic' ;;
  }

  # Row-level spend, for the mature-cohort ROAS measures in cohorts.view.lkml.
  dimension: spend_amount {
    hidden: yes
    type: number
    sql: ${TABLE}.spend ;;
  }

  # ---- Measures ------------------------------------------------------------------------------

  measure: spend {
    label: "Spend"
    description: "Paid media spend in USD for the cohorts in the query, all install dates. Organic is excluded (it has no spend)."
    type: sum
    sql: ${spend_amount} ;;
    filters: [is_paid: "yes"]
    value_format_name: usd_0
  }

  measure: paid_installs {
    label: "Paid Installs"
    description: "Installs from paid channels, from the spend table. Equals cohort installs for the same paid cohorts."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_paid: "yes"]
    value_format_name: decimal_0
  }

  measure: cpi {
    label: "CPI"
    description: "Cost per install: paid spend divided by paid installs, in USD. Organic is excluded from both."
    type: number
    sql: ${spend} * 1.0 / NULLIF(${paid_installs}, 0) ;;
    value_format_name: usd
  }
}
