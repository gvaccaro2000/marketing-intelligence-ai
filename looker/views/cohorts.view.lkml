# Install cohorts. Grain: install_date x channel x campaign x country x platform (no creative_id).
#
# Maturity (data as of 2026-08-29): a cohort's Dn columns are NULL until day n has passed
#   D1 mature: install_date <= 2026-08-28
#   D7 mature: install_date <= 2026-08-22
#   D30 mature: install_date <= 2026-07-30
# Every Dn ratio drops immature cohorts from BOTH numerator and denominator, by filtering the
# denominator on the same column being NOT NULL. NULL is never treated as 0.
#
# Revenue columns are cumulative (revenue_d0 <= revenue_d7 <= revenue_d30): never add them up.
# ROAS needs spend, which comes from spend_cohort_grain; use these measures in ua_performance.

view: cohorts {
  sql_table_name: marketing.cohorts ;;

  # ---- Keys ----------------------------------------------------------------------------------

  dimension: pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CAST(${TABLE}.install_date AS VARCHAR) || '|' || ${TABLE}.channel || '|' || ${TABLE}.campaign
      || '|' || ${TABLE}.country || '|' || ${TABLE}.platform ;;
  }

  # ---- Dimensions ----------------------------------------------------------------------------

  dimension_group: install {
    label: "Install"
    description: "Cohort install date. Weeks run Monday to Sunday."
    type: time
    datatype: date
    convert_tz: no
    timeframes: [raw, date, week, month]
    sql: ${TABLE}.install_date ;;
  }

  dimension: channel {
    description: "Acquisition channel: Meta, Google, AppLovin, Unity, TikTok or Organic."
    type: string
    sql: ${TABLE}.channel ;;
  }

  dimension: campaign {
    description: "Campaign name. Organic has one pseudo-campaign called organic."
    type: string
    sql: ${TABLE}.campaign ;;
  }

  dimension: country {
    description: "Country of the install: US, UK, DE, JP, BR or FR."
    type: string
    sql: ${TABLE}.country ;;
  }

  dimension: platform {
    description: "Device platform: iOS or Android."
    type: string
    sql: ${TABLE}.platform ;;
  }

  dimension: is_paid {
    label: "Is Paid"
    description: "Yes for paid channels, No for Organic."
    type: yesno
    sql: ${TABLE}.channel <> 'Organic' ;;
  }

  # Maturity flags: one per metric column, so each ratio filters on the column it uses.
  dimension: is_d1_mature {
    label: "Is D1 Mature"
    description: "Yes when the cohort is old enough to have day-1 retention."
    type: yesno
    sql: ${TABLE}.d1_retained IS NOT NULL ;;
  }

  dimension: is_d7_mature {
    label: "Is D7 Mature"
    description: "Yes when the cohort is old enough to have day-7 retention."
    type: yesno
    sql: ${TABLE}.d7_retained IS NOT NULL ;;
  }

  dimension: is_d30_mature {
    label: "Is D30 Mature"
    description: "Yes when the cohort is old enough to have day-30 retention."
    type: yesno
    sql: ${TABLE}.d30_retained IS NOT NULL ;;
  }

  dimension: is_d7_revenue_mature {
    label: "Is D7 Revenue Mature"
    description: "Yes when the cohort has its full 7-day revenue."
    type: yesno
    sql: ${TABLE}.revenue_d7 IS NOT NULL ;;
  }

  dimension: is_d30_revenue_mature {
    label: "Is D30 Revenue Mature"
    description: "Yes when the cohort has its full 30-day revenue."
    type: yesno
    sql: ${TABLE}.revenue_d30 IS NOT NULL ;;
  }

  dimension: is_payers_d7_mature {
    hidden: yes
    type: yesno
    sql: ${TABLE}.payers_d7 IS NOT NULL ;;
  }

  # ---- Measures: volume ----------------------------------------------------------------------

  measure: installs {
    label: "Cohort Installs"
    description: "Users who installed in the cohorts in the query, paid and Organic. Filter Is Paid to split them."
    type: sum
    sql: ${TABLE}.installs ;;
    value_format_name: decimal_0
  }

  # ---- Measures: retention -------------------------------------------------------------------

  measure: d1_retained {
    label: "D1 Retained Users"
    description: "Users active on day 1 after install. Only cohorts old enough to have day-1 data count."
    type: sum
    sql: ${TABLE}.d1_retained ;;
    filters: [is_d1_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d1_mature_installs {
    label: "D1 Mature Installs"
    description: "Installs in cohorts old enough to have day-1 data. Denominator of D1 retention."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_d1_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d1_retention {
    label: "D1 Retention"
    description: "Share of installers active on day 1, using only cohorts old enough to have day-1 data."
    type: number
    sql: ${d1_retained} * 1.0 / NULLIF(${d1_mature_installs}, 0) ;;
    value_format_name: percent_1
  }

  measure: d7_retained {
    label: "D7 Retained Users"
    description: "Users active on day 7 after install. Only cohorts old enough to have day-7 data count."
    type: sum
    sql: ${TABLE}.d7_retained ;;
    filters: [is_d7_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d7_mature_installs {
    label: "D7 Mature Installs"
    description: "Installs in cohorts old enough to have day-7 data. Denominator of D7 retention."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_d7_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d7_retention {
    label: "D7 Retention"
    description: "Share of installers active on day 7, using only cohorts old enough to have day-7 data."
    type: number
    sql: ${d7_retained} * 1.0 / NULLIF(${d7_mature_installs}, 0) ;;
    value_format_name: percent_1
  }

  measure: d30_retained {
    label: "D30 Retained Users"
    description: "Users active on day 30 after install. Only cohorts old enough to have day-30 data count."
    type: sum
    sql: ${TABLE}.d30_retained ;;
    filters: [is_d30_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d30_mature_installs {
    label: "D30 Mature Installs"
    description: "Installs in cohorts old enough to have day-30 data. Denominator of D30 retention."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_d30_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: d30_retention {
    label: "D30 Retention"
    description: "Share of installers active on day 30, using only cohorts old enough to have day-30 data."
    type: number
    sql: ${d30_retained} * 1.0 / NULLIF(${d30_mature_installs}, 0) ;;
    value_format_name: percent_1
  }

  # ---- Measures: revenue and payers ----------------------------------------------------------

  measure: revenue_d7 {
    label: "D7 Revenue"
    description: "Revenue in USD from each cohort's first 7 days, cumulative. Only cohorts with a full 7 days count. Paid and Organic."
    type: sum
    sql: ${TABLE}.revenue_d7 ;;
    filters: [is_d7_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: revenue_d30 {
    label: "D30 Revenue"
    description: "Revenue in USD from each cohort's first 30 days, cumulative. Only cohorts with a full 30 days count. Paid and Organic."
    type: sum
    sql: ${TABLE}.revenue_d30 ;;
    filters: [is_d30_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: payers_d7 {
    label: "D7 Payers"
    description: "Users who made a purchase within 7 days of install. Only cohorts with a full 7 days count."
    type: sum
    sql: ${TABLE}.payers_d7 ;;
    filters: [is_payers_d7_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: payers_d7_mature_installs {
    label: "D7 Payer Base Installs"
    description: "Installs in cohorts with a full 7 days of payer data. Denominator of D7 payer conversion."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_payers_d7_mature: "yes"]
    value_format_name: decimal_0
  }

  measure: payer_conversion_d7 {
    label: "D7 Payer Conversion"
    description: "Share of installers who paid within 7 days of install (cohort payer conversion), using only cohorts with a full 7 days."
    type: number
    sql: ${payers_d7} * 1.0 / NULLIF(${payers_d7_mature_installs}, 0) ;;
    value_format_name: percent_2
  }

  # ---- Measures: ROAS (paid only, mature cohorts only) ---------------------------------------
  # Numerator and spend denominator use the SAME rows: paid cohorts whose revenue_dN is not NULL.
  # Dropping only the revenue of young cohorts but keeping their spend would understate ROAS.

  measure: paid_revenue_d7 {
    label: "Paid D7 Revenue"
    description: "D7 revenue in USD from paid cohorts with a full 7 days. Numerator of D7 ROAS."
    type: sum
    sql: ${TABLE}.revenue_d7 ;;
    filters: [is_paid: "yes", is_d7_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: spend_d7_mature {
    label: "Spend on D7-Mature Cohorts"
    description: "Paid spend in USD that acquired cohorts with a full 7 days of revenue. Denominator of D7 ROAS."
    type: sum
    sql: ${spend_cohort_grain.spend_amount} ;;
    filters: [is_paid: "yes", is_d7_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: roas_d7 {
    label: "D7 ROAS"
    description: "Return on ad spend after 7 days: paid D7 revenue divided by the spend that acquired the same cohorts. Only cohorts with a full 7 days count, on both sides. Organic is excluded."
    type: number
    sql: ${paid_revenue_d7} * 1.0 / NULLIF(${spend_d7_mature}, 0) ;;
    value_format_name: percent_1
  }

  measure: paid_revenue_d30 {
    label: "Paid D30 Revenue"
    description: "D30 revenue in USD from paid cohorts with a full 30 days. Numerator of D30 ROAS."
    type: sum
    sql: ${TABLE}.revenue_d30 ;;
    filters: [is_paid: "yes", is_d30_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: spend_d30_mature {
    label: "Spend on D30-Mature Cohorts"
    description: "Paid spend in USD that acquired cohorts with a full 30 days of revenue. Denominator of D30 ROAS."
    type: sum
    sql: ${spend_cohort_grain.spend_amount} ;;
    filters: [is_paid: "yes", is_d30_revenue_mature: "yes"]
    value_format_name: usd_0
  }

  measure: roas_d30 {
    label: "D30 ROAS"
    description: "Return on ad spend after 30 days: paid D30 revenue divided by the spend that acquired the same cohorts. Only cohorts with a full 30 days count, on both sides. Organic is excluded."
    type: number
    sql: ${paid_revenue_d30} * 1.0 / NULLIF(${spend_d30_mature}, 0) ;;
    value_format_name: percent_1
  }
}
