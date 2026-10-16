# Paid-media delivery. Grain: date x channel x campaign x country x platform x creative_id.
# Organic rows carry installs only (spend, impressions and clicks are always 0).
# Every paid measure (spend, impressions, clicks, paid installs, CPI, CTR, IPM) is filtered to
# is_paid = yes, so Organic can never lower CPI or dilute CTR/IPM, whatever the query filters.

view: ua_spend {
  sql_table_name: marketing.ua_spend ;;

  # ---- Keys ----------------------------------------------------------------------------------

  dimension: pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CAST(${TABLE}."date" AS VARCHAR) || '|' || ${TABLE}.channel || '|' || ${TABLE}.campaign
      || '|' || ${TABLE}.country || '|' || ${TABLE}.platform || '|' || ${TABLE}.creative_id ;;
  }

  # ---- Dimensions ----------------------------------------------------------------------------

  dimension_group: date {
    label: "Activity"
    description: "Delivery date. For installs this is also the install date. Weeks run Monday to Sunday."
    type: time
    datatype: date
    convert_tz: no
    timeframes: [raw, date, week, month]
    sql: ${TABLE}."date" ;;
  }

  dimension: channel {
    description: "Acquisition channel: Meta, Google, AppLovin, Unity, TikTok or Organic."
    type: string
    sql: ${TABLE}.channel ;;
  }

  dimension: campaign {
    description: "Campaign name. Each paid channel runs two campaigns; Organic has one pseudo-campaign called organic."
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

  dimension: creative_id {
    label: "Creative ID"
    description: "Ad creative. Only this table has creative detail, so cohort metrics (retention, revenue, ROAS) cannot be split by creative."
    type: string
    sql: ${TABLE}.creative_id ;;
  }

  dimension: is_paid {
    label: "Is Paid"
    description: "Yes for paid channels, No for Organic."
    type: yesno
    sql: ${TABLE}.channel <> 'Organic' ;;
  }

  # ---- Measures ------------------------------------------------------------------------------

  measure: spend {
    label: "Spend"
    description: "Paid media spend in USD. Organic is excluded (it has no spend)."
    type: sum
    sql: ${TABLE}.spend ;;
    filters: [is_paid: "yes"]
    value_format_name: usd_0
  }

  measure: impressions {
    label: "Impressions"
    description: "Paid ad impressions. Organic is excluded."
    type: sum
    sql: ${TABLE}.impressions ;;
    filters: [is_paid: "yes"]
    value_format_name: decimal_0
  }

  measure: clicks {
    label: "Clicks"
    description: "Paid ad clicks. Organic is excluded."
    type: sum
    sql: ${TABLE}.clicks ;;
    filters: [is_paid: "yes"]
    value_format_name: decimal_0
  }

  measure: installs {
    label: "Installs (All)"
    description: "All attributed installs, paid and Organic. Use Paid Installs for anything compared with spend."
    type: sum
    sql: ${TABLE}.installs ;;
    value_format_name: decimal_0
  }

  measure: paid_installs {
    label: "Paid Installs"
    description: "Installs from paid channels only. Organic is excluded."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_paid: "yes"]
    value_format_name: decimal_0
  }

  measure: organic_installs {
    label: "Organic Installs"
    description: "Installs from the Organic channel. Context only; not used in any paid ratio."
    type: sum
    sql: ${TABLE}.installs ;;
    filters: [is_paid: "no"]
    value_format_name: decimal_0
  }

  measure: cpi {
    label: "CPI"
    description: "Cost per install: paid spend divided by paid installs, in USD. Organic is excluded from both."
    type: number
    sql: ${spend} * 1.0 / NULLIF(${paid_installs}, 0) ;;
    value_format_name: usd
  }

  measure: ctr {
    label: "CTR"
    description: "Click-through rate: paid clicks divided by paid impressions. Organic is excluded."
    type: number
    sql: ${clicks} * 1.0 / NULLIF(${impressions}, 0) ;;
    value_format_name: percent_2
  }

  measure: ipm {
    label: "IPM"
    description: "Installs per mille: paid installs per 1,000 paid impressions. Organic is excluded."
    type: number
    sql: ${paid_installs} * 1000.0 / NULLIF(${impressions}, 0) ;;
    value_format_name: decimal_2
  }
}
