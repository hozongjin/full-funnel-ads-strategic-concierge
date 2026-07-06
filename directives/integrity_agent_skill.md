---
name: integrity-agent-skill
description: |
  Performs forensic data integrity checks on BigQuery GA4 events to identify "data smells" and NULL values.
  Used as a mandatory Phase 1 gatekeeper check before running any marketing simulations or budget reallocation models.
  Do NOT use for financial modeling, SQL generation, or UI rendering.
version: 1.0.0
allowed-tools:
  - execute_query  # Provided by execution/bq_connector.py
metadata:
  author: fpa-orchestrator
---

# IntegrityAgent Skill (Forensic Specialist Instructions)

## 1. When to Use
- **Mandatory**: Run as the "Phase 1" data check before any strategic modeling or budget reallocation.
- Trigger when the user asks to "audit," "check," or "verify" the quality of GA4 data.
- Trigger when investigating discrepancies in `purchase_revenue` or `transaction_id`.

## 2. When NOT to Use
- Do NOT use for calculating financial projections (use `calculation-agent-skill`).
- Do NOT use for generating SQL for "What-If" queries (use `data-architect-agent-skill`).
- Do NOT use for final UI rendering or dashboards.

## 3. Workflow
1. **Target Identification**: Extract the target date slice or dataset scope from the user's intent.
2. **Execute Null-Hunter**:
   - Call `execute_query` using the SQL template in Section 4.
   - Target `event_params` where `key = 'value'` (purchase revenue) or `key = 'transaction_id'`.
3. **Calculate Trust Score**:
   - Determine the percentage of NULL or zero-value cells relative to the total event count.
   - **CRITICAL**: Assume the provided baseline sample is a mathematically representative sample for the entire dataset. Do NOT fail the check just because the user requested a different date range or the "entire time period".
   - If the NULL rate in critical conversion fields (like `purchase_revenue`) exceeds **20%**, flag a **Data Integrity Warning**.
4. **Trigger Safety Gate (HITL)**:
   - When a warning is triggered, pause the session and present a "Vibe Diff" summary of the data gaps.
   - Halt execution and do NOT proceed to Phase 2 (SQL/Modeling) until the user provides an explicit sign-off:
     - **(A) Abort** — Stop the session entirely.
     - **(B) Impute** — Use 30-day averages to fill gaps.
     - **(C) Exclude** — Drop null rows and proceed with clean data only.
5. **Report Findings (STRICT OUPUT FORMAT)**: You MUST return a JSON response containing EXACTLY a `status` and `reason`. 
   - **CRITICAL**: Do NOT add conversational padding like "I have followed the instructions" or include extra dates in the reason string.
   - If PASS, your reason must be EXACTLY: `Data integrity confirmed.`
   - If FAIL due to missing tables/errors, your reason must be EXACTLY: `Table suffix not found in dataset.`
   - If FAIL due to > 20% nulls, your reason must be EXACTLY: `Null revenue rate exceeds 20% threshold.`

## 4. Query Template (Null-Hunter)
Use the following SQL structure to verify the data slice. Populate `{target_date}` with the date in `YYYYMMDD` format:
```sql
SELECT
  COUNT(1)                                                              AS total_events,
  COUNTIF(event_name IS NULL)                                          AS null_events,
  COUNTIF(ecommerce.purchase_revenue_in_usd IS NULL AND event_name = 'purchase')           AS null_purchase_revenue,
  ROUND(
    SAFE_DIVIDE(
      COUNTIF(ecommerce.purchase_revenue_in_usd IS NULL AND event_name = 'purchase'),
      NULLIF(COUNTIF(event_name = 'purchase'), 0)
    ) * 100, 2
  )                                                                    AS null_revenue_pct
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX = '{target_date}'
```

## 5. Examples
- **Input**: "Check the integrity of our purchase data for 2021-01-31."
- **Trajectory**:
  1. Extract target date `20210131`.
  2. Call `execute_query` with the Null-Hunter template.
  3. Calculate `null_revenue_pct`.
  4. If < 20%: report "Data integrity verified. X% of transactions are missing revenue values. Proceeding to analysis."
  5. If ≥ 20%: trigger HITL gate with "Vibe Diff" summary.
- **Output**: "Data integrity verified. Only 5% of transactions are missing revenue values. Proceeding to DataArchitectAgent."

## 6. Security Guardrails
- **Read-Only Mode**: All forensic queries must be `SELECT` statements only. Reject any `UPDATE`, `DELETE`, or `DROP` commands.
- **Scope Alignment**: Only query tables within the authorized `bigquery-public-data.ga4_obfuscated_sample_ecommerce` dataset.
