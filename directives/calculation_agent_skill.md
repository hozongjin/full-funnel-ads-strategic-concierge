---
name: calculation-agent-skill
description: |
  Performs deterministic financial math calculations (ROAS, CVR, Gross Profit) on GA4 datasets.
  Integrates BigQuery query results with budget and cost inputs from master_data.yaml.
  Do NOT generate SQL queries or run forensic data integrity audits.
version: 1.0.0
allowed-tools: []
metadata:
  author: fpa-orchestrator
---

# CalculationAgent Skill (Financial Modeler Instructions)

## 1. When to Use
- **Mandatory Phase 2 Step**: Run after the DataArchitectAgent successfully retrieves the baseline data slice from BigQuery.
- Trigger when the user wants to calculate ROI, ROAS, CPA, Conversion Rates (CVR), or Gross Profit.
- Trigger when modeling budget reallocation scenarios (e.g. "shift 20% of Google Ads budget to Email").

## 2. When NOT to Use
- Do NOT use for checking data quality or identifying null events (use `integrity-agent-skill`).
- Do NOT use for writing SQL or querying BigQuery directly (use `data-architect-agent-skill`).
- Do NOT use for rendering visual dashboards.

## 3. Workflow
1. **Load Master Data**: Read `config/master_data.yaml` to retrieve the current budget allocations (`channel_spend_usd_monthly`), proxy CPCs (`channel_cpc_proxy_usd`), gross margin rates (`gross_margin_by_category`), and global assumptions.
2. **Map GA4 Results**: Align the BigQuery query results (total sessions, purchases, and purchase revenue) to the channel mediums present in `master_data.yaml`.
3. **Execute Core Math**: Apply the deterministic formulas in Section 4 to calculate baseline metrics.
4. **Model Scenario Shift** (If requested): Apply the reallocation math in Section 4 to project the revenue and ROAS changes.
5. **Format & Alert**: Output a Markdown table summarizing the metrics, flagging any channel with a warning (⚠️) if its ROAS is below the `roas_alert_threshold`.

---

## 4. Calculation Templates & Formulas

### Formula A: Baseline CVR
Calculate the Purchase Conversion Rate per channel medium:
$$\text{CVR (\%)} = \left( \frac{\text{Total Purchases}}{\text{Total Sessions}} \right) \times 100$$
*Parameters:*
- `Total Purchases`: Handled as `total_purchases` from BQ.
- `Total Sessions`: Handled as `total_sessions` from BQ.

### Formula B: Baseline ROAS
Calculate the Return on Ad Spend per channel medium:
$$\text{Spend} = \text{Spend Value from master\_data.yaml (pro-rated to query date range)}$$
$$\text{ROAS} = \frac{\text{Total Revenue}}{\text{Spend}}$$
*Parameters:*
- `Total Revenue`: Handled as `total_revenue` from BQ.
- `Spend`: If `spend_input_method` is `"monthly_budget"`, divide the channel's monthly spend by 30 and multiply by the number of days in the query date range. If `"cpc_proxy"`, calculate `Spend = Total Sessions × CPC Proxy`.

### Formula C: Spend Reallocation Scenario
When shifting budget ($X$) from **Channel A (Source)** to **Channel B (Target)**:
1. **Reduce Source Spend**:
   $$\text{New Spend A} = \text{Spend A} - X$$
   $$\text{New Revenue A} = \text{New Spend A} \times \text{ROAS A}$$
2. **Increase Target Spend**:
   $$\text{New Spend B} = \text{Spend B} + X$$
   $$\text{New Revenue B} = \text{New Spend B} \times \text{ROAS B}$$
3. **Calculate System Impact**:
   $$\text{Net Revenue Delta} = (\text{New Revenue A} + \text{New Revenue B}) - (\text{Revenue A} + \text{Revenue B})$$
   $$\text{New Combined ROAS} = \frac{\text{New Revenue A} + \text{New Revenue B}}{\text{New Spend A} + \text{New Spend B}}$$

### Formula D: Baseline CPA
Calculate the Cost Per Acquisition (CPA) per channel medium:
$$\text{CPA} = \frac{\text{Spend}}{\text{Total Purchases}}$$
*Parameters:*
- `Spend`: Derived as in Formula B.
- `Total Purchases`: Handled as `total_purchases` from BQ.

### Formula E: Gross Profit & Contribution Margin
Calculate the product margin and contribution margin (net cash generated after ad costs):
$$\text{Gross Profit} = \sum_{\text{items}} (\text{Item Revenue} \times \text{Item Category Margin Rate})$$
$$\text{Contribution Margin} = \text{Gross Profit} - \text{Spend}$$
*Parameters:*
- `Item Revenue` & `Item Category Margin Rate`: Extracted by category from the `items` array matching the rates in `master_data.yaml` under `gross_margin_by_category`. If item-level detail is missing or category is unmapped, fall back to the global `default` margin rate.

### Formula F: Revenue Per Session (RPC) vs. CPC
Calculate the Revenue Per Session (RPC) to evaluate unit economics:
$$\text{RPC} = \frac{\text{Total Revenue}}{\text{Total Sessions}}$$
$$\text{Net Unit Profit} = \text{RPC} - \text{CPC}$$
*Parameters:*
- `Total Revenue`: Handled as `total_revenue` from BQ.
- `Total Sessions`: Handled as `total_sessions` from BQ.
- `CPC`: Loaded from `channel_cpc_proxy_usd` in `master_data.yaml` (or computed as `Spend / Total Sessions`).

### Formula G: Upper Funnel Metrics
Based on `first_visit` and `session_start` events:
- **Total Unique Users**: Count of distinct `user_pseudo_id`.
- **Engaged Sessions**: Sessions where the `session_engaged` parameter equals `1` (CRITICAL: check both `value.string_value = '1'` and `value.int_value = 1` due to GA4 schema quirks), OR sessions that trigger a `user_engagement` event.
- **Bounce/Engagement Rate**: Engaged sessions / Total sessions (`session_start`).
- **Cost Per Engaged Session**: `Spend / Engaged Sessions`.

### Formula H: Mid Funnel Metrics
Based on `view_item` and `add_to_cart` events:
- **View-to-Cart Conversion Ratio**: `Total add_to_cart / Total view_item`.
- **Cart Abandonment Rate**: `1 - (Total purchase / Total add_to_cart)`.
- **Category Item Views**: Number of `view_item` events segmented by item category.

### Formula I: Lower Funnel Metrics
Based on `begin_checkout` and `purchase` events:
- **E-commerce Conversion Rate (ECR)**: `Total purchase / Total session_start` (or total unique users).
- **Average Order Value (AOV)**: `Total Revenue / Total purchase`.
- **Revenue per Active User**: `Total Revenue / Total Unique Users`.

---

## 5. Examples

### Scenario: Reallocation Shift
- **Input**: Query results showing `cpc` has $5000 revenue & $2000 spend (ROAS = 2.5); `email` has $3000 revenue & $500 spend (ROAS = 6.0). User asks: "Shift $1000 from cpc to email".
- **Trajectory**:
  1. Source channel: `cpc`. Target channel: `email`. Shift amount: $1000.
  2. Calculate new spend: `New CPC Spend` = $1000. `New Email Spend` = $1500.
  3. Calculate new revenue: `New CPC Revenue` = $1000 * 2.5 = $2500. `New Email Revenue` = $1500 * 6.0 = $9000.
  4. System impact: Combined spend is unchanged ($2500). Original combined revenue was $8000. New combined revenue is $11500.
  5. Net Impact: +$3500 Revenue increase. ROAS rises from 3.2 to 4.6.
- **Output**: Detailed Markdown table comparing "Before" vs "After" metrics, showing delta.

---

## 6. Security & Verification Guardrails
- **No Direct Inputs**: All spend figures and CPCs must be fetched from `master_data.yaml`. Never hardcode cost figures in calculations.
- **Zero Divisors**: Always use safe division checks to prevent division-by-zero errors when a channel has 0 spend or 0 sessions.
