# Game-wide daily KPIs. Grain: date x platform. All users, paid and Organic.
# No channel, campaign or country, so these numbers cannot be attributed to UA sources.
# dau and payers are daily distinct counts: summed over several days they count user-days,
# not unique users. Use the sums only inside ratios (ARPDAU, daily payer rate).

view: daily_kpis {
  sql_table_name: marketing.daily_kpis ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    type: string
    sql: CAST(${TABLE}."date" AS VARCHAR) || '|' || ${TABLE}.platform ;;
  }

  dimension_group: date {
    label: "Activity"
    description: "Activity date. Weeks run Monday to Sunday."
    type: time
    datatype: date
    convert_tz: no
    timeframes: [raw, date, week, month]
    sql: ${TABLE}."date" ;;
  }

  dimension: platform {
    description: "Device platform: iOS or Android."
    type: string
    sql: ${TABLE}.platform ;;
  }

  measure: dau {
    label: "DAU (User-Days)"
    description: "Daily active users. Over one day this is a user count; over several days it adds up user-days, not unique users."
    type: sum
    sql: ${TABLE}.dau ;;
    value_format_name: decimal_0
  }

  measure: average_dau {
    label: "Average DAU"
    description: "Average daily active users per day across the selected dates (user-days divided by the number of days)."
    type: number
    sql: ${dau} * 1.0 / NULLIF(COUNT(DISTINCT ${TABLE}."date"), 0) ;;
    value_format_name: decimal_0
  }

  measure: revenue {
    label: "Revenue"
    description: "Total game revenue in USD from all users, paid and Organic, on the selected dates."
    type: sum
    sql: ${TABLE}.revenue ;;
    value_format_name: usd_0
  }

  measure: payers {
    label: "Payers (User-Days)"
    description: "Users who paid on each day. Over several days this adds up payer-days, not unique payers."
    type: sum
    sql: ${TABLE}.payers ;;
    value_format_name: decimal_0
  }

  measure: arpdau {
    label: "ARPDAU"
    description: "Average revenue per daily active user, in USD: revenue divided by DAU user-days. All users."
    type: number
    sql: ${revenue} * 1.0 / NULLIF(${dau}, 0) ;;
    value_format_name: usd
  }

  measure: daily_payer_rate {
    label: "Daily Payer Rate"
    description: "Share of daily active users who paid that day: payer-days divided by DAU user-days. Not the same as D7 payer conversion."
    type: number
    sql: ${payers} * 1.0 / NULLIF(${dau}, 0) ;;
    value_format_name: percent_2
  }
}
