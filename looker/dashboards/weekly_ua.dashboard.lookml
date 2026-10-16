# Weekly UA dashboard. All tiles use the ua_performance explore (cohorts + spend at cohort grain),
# so spend, installs, CPI and ROAS share one install-date filter and one definition of each metric.
# D7 ROAS only counts cohorts with a full 7 days of revenue (numerator and spend denominator), so
# the most recent week shows ROAS on its mature days only.

- dashboard: weekly_ua
  title: "Weekly UA Performance"
  description: "Paid spend, installs, CPI and D7 ROAS by week, channel and country. Organic is excluded from every paid metric; D7 ROAS uses only cohorts with a full 7 days of revenue."
  layout: newspaper
  preferred_viewer: dashboards-next
  crossfilter_enabled: true

  filters:
  - name: install_date
    title: "Install Date"
    type: field_filter
    # Complete Monday-Sunday weeks in the data (as of 2026-08-29); the end date is exclusive.
    default_value: "2026/06/01 to 2026/08/24"
    allow_multiple_values: true
    required: false
    ui_config:
      type: advanced
      display: popover
    model: marketing
    explore: ua_performance
    field: cohorts.install_date

  - name: channel
    title: "Channel"
    type: field_filter
    default_value: ""
    allow_multiple_values: true
    required: false
    ui_config:
      type: tag_list
      display: popover
    model: marketing
    explore: ua_performance
    field: cohorts.channel

  - name: country
    title: "Country"
    type: field_filter
    default_value: ""
    allow_multiple_values: true
    required: false
    ui_config:
      type: tag_list
      display: popover
    model: marketing
    explore: ua_performance
    field: cohorts.country

  - name: platform
    title: "Platform"
    type: field_filter
    default_value: ""
    allow_multiple_values: true
    required: false
    ui_config:
      type: button_toggles
      display: inline
    model: marketing
    explore: ua_performance
    field: cohorts.platform

  elements:
  # ---- KPI tiles -----------------------------------------------------------------------------
  - name: kpi_spend
    title: "Paid Spend"
    model: marketing
    explore: ua_performance
    type: single_value
    fields: [spend_cohort_grain.spend]
    note_text: "Paid channels only."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 0
    col: 0
    width: 6
    height: 3

  - name: kpi_installs
    title: "Paid Installs"
    model: marketing
    explore: ua_performance
    type: single_value
    fields: [spend_cohort_grain.paid_installs]
    note_text: "Paid channels only; Organic installs are excluded."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 0
    col: 6
    width: 6
    height: 3

  - name: kpi_cpi
    title: "CPI"
    model: marketing
    explore: ua_performance
    type: single_value
    fields: [spend_cohort_grain.cpi]
    note_text: "Paid spend / paid installs."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 0
    col: 12
    width: 6
    height: 3

  - name: kpi_roas_d7
    title: "D7 ROAS"
    model: marketing
    explore: ua_performance
    type: single_value
    fields: [cohorts.roas_d7]
    note_text: "D7-mature paid cohorts only (installs on or before 2026-08-22)."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 0
    col: 18
    width: 6
    height: 3

  # ---- Weekly spend trend --------------------------------------------------------------------
  - name: weekly_spend_trend
    title: "Weekly Paid Spend by Channel"
    model: marketing
    explore: ua_performance
    type: looker_column
    fields: [cohorts.install_week, cohorts.channel, spend_cohort_grain.spend]
    pivots: [cohorts.channel]
    filters:
      cohorts.is_paid: "Yes"
    sorts: [cohorts.install_week, cohorts.channel]
    stacking: normal
    show_totals_labels: true
    x_axis_label: "Install week (Mon-Sun)"
    y_axis_labels: ["Spend (USD)"]
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 3
    col: 0
    width: 24
    height: 8

  # ---- D7 ROAS breakdowns --------------------------------------------------------------------
  - name: roas_d7_by_channel
    title: "D7 ROAS by Channel"
    model: marketing
    explore: ua_performance
    type: looker_bar
    fields: [cohorts.channel, cohorts.roas_d7, cohorts.paid_revenue_d7, cohorts.spend_d7_mature]
    hidden_fields: [cohorts.paid_revenue_d7, cohorts.spend_d7_mature]
    filters:
      cohorts.is_paid: "Yes"
    sorts: [cohorts.roas_d7 desc]
    show_value_labels: true
    note_text: "Paid D7 revenue / spend on the same D7-mature cohorts."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 11
    col: 0
    width: 12
    height: 8

  - name: roas_d7_by_country
    title: "D7 ROAS by Country"
    model: marketing
    explore: ua_performance
    type: looker_bar
    fields: [cohorts.country, cohorts.roas_d7, cohorts.paid_revenue_d7, cohorts.spend_d7_mature]
    hidden_fields: [cohorts.paid_revenue_d7, cohorts.spend_d7_mature]
    filters:
      cohorts.is_paid: "Yes"
    sorts: [cohorts.roas_d7 desc]
    show_value_labels: true
    note_text: "Paid D7 revenue / spend on the same D7-mature cohorts."
    listen:
      install_date: cohorts.install_date
      channel: cohorts.channel
      country: cohorts.country
      platform: cohorts.platform
    row: 11
    col: 12
    width: 12
    height: 8
