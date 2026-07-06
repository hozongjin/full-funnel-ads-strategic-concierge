# /// script
# dependencies = [
#   "pyyaml",
# ]
# ///

"""
Calculation Engine — Deterministic financial math for the CalculationAgent.

All formulas match those defined in directives/calculation_agent_skill.md.
This module performs pure math on data passed in; it never queries BigQuery directly.
"""

import config_loader


def safe_divide(numerator: float, denominator: float) -> float:
    """Division with zero-denominator protection."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def calculate_baseline_metrics(
    channel_data: list[dict],
    master_data: dict,
    num_days: int,
) -> list[dict]:
    """Calculates CVR, ROAS, CPA, RPC, and Contribution Margin for each channel.

    Args:
        channel_data: List of dicts from BigQuery, each containing:
            - channel_medium (str)
            - total_sessions (int)
            - total_revenue (float)
            - total_purchases (int)
        master_data: The loaded master_data.yaml dict.
        num_days: Number of days in the query date range.

    Returns:
        List of dicts with original fields plus computed metrics.
    """
    assumptions = config_loader.get_assumptions(master_data)
    method = assumptions.get("spend_input_method", "monthly_budget")
    roas_threshold = assumptions.get("roas_alert_threshold", 2.0)
    cpc_proxies = config_loader.get_channel_cpc(master_data)
    default_margin = config_loader.get_margin_for_category(master_data, "__default__")

    results = []
    for row in channel_data:
        medium = row.get("channel_medium", "(unknown)")
        sessions = row.get("total_sessions", 0)
        revenue = row.get("total_revenue", 0.0) or 0.0
        purchases = row.get("total_purchases", 0)

        # --- Spend ---
        if method == "monthly_budget":
            spend = config_loader.get_spend_for_channel(master_data, medium, num_days)
        else:
            cpc = cpc_proxies.get(medium, 0.0)
            spend = sessions * cpc

        # --- Formula A: CVR ---
        cvr = safe_divide(purchases, sessions) * 100

        # --- Formula B: ROAS ---
        roas = safe_divide(revenue, spend)

        # --- Formula D: CPA ---
        cpa = safe_divide(spend, purchases)

        # --- Formula E: Gross Profit & Contribution Margin ---
        # Use the blended default margin when item-level data is not available
        gross_profit = revenue * default_margin
        contribution_margin = gross_profit - spend

        # --- Formula F: RPC vs CPC ---
        rpc = safe_divide(revenue, sessions)
        cpc_rate = cpc_proxies.get(medium, 0.0)
        net_unit_profit = rpc - cpc_rate

        # --- Alert ---
        roas_alert = spend > 0 and roas < roas_threshold

        results.append({
            "channel_medium": medium,
            "sessions": sessions,
            "purchases": purchases,
            "revenue": round(revenue, 2),
            "spend": round(spend, 2),
            "cvr_pct": round(cvr, 2),
            "roas": round(roas, 2),
            "cpa": round(cpa, 2),
            "gross_profit": round(gross_profit, 2),
            "contribution_margin": round(contribution_margin, 2),
            "rpc": round(rpc, 4),
            "cpc": round(cpc_rate, 4),
            "net_unit_profit": round(net_unit_profit, 4),
            "roas_alert": roas_alert,
        })

    return results


def calculate_upper_funnel_metrics(data: dict) -> dict:
    """Formula G: Upper Funnel metrics from raw atomic counts."""
    res = {}
    total_sessions = data.get("total_sessions")
    engaged_sessions = data.get("engaged_sessions")
    spend = data.get("spend")
    
    if total_sessions is not None and engaged_sessions is not None:
        res["bounce_rate"] = round(1 - safe_divide(engaged_sessions, total_sessions), 4)
        res["engagement_rate"] = round(safe_divide(engaged_sessions, total_sessions), 4)
        
    if engaged_sessions is not None and spend is not None:
        res["cost_per_engaged_session"] = round(safe_divide(spend, engaged_sessions), 2)

    return res


def calculate_mid_funnel_metrics(data: dict) -> dict:
    """Formula H: Mid Funnel metrics from raw atomic counts."""
    res = {}
    views = data.get("total_view_item")
    carts = data.get("total_add_to_cart")
    purchases = data.get("total_purchases")

    if carts is not None and views is not None:
        res["view_to_cart_ratio"] = round(safe_divide(carts, views), 4)
        
    if purchases is not None and carts is not None:
        res["cart_abandonment_rate"] = round(1 - safe_divide(purchases, carts), 4)

    return res


def calculate_lower_funnel_metrics(data: dict) -> dict:
    """Formula I: Lower Funnel metrics from raw atomic counts."""
    res = {}
    purchases = data.get("total_purchases")
    revenue = data.get("total_revenue")
    sessions = data.get("total_sessions")
    unique_users = data.get("total_unique_users")

    if purchases is not None and sessions is not None:
        res["ecr"] = round(safe_divide(purchases, sessions), 4)
        
    if revenue is not None and purchases is not None:
        res["aov"] = round(safe_divide(revenue, purchases), 2)
        
    if revenue is not None and unique_users is not None:
        res["revenue_per_user"] = round(safe_divide(revenue, unique_users), 2)

    return res


def calculate_reallocation(
    baseline_results: list[dict],
    source_channel: str,
    target_channel: str,
    shift_amount: float,
) -> dict:
    """Models a budget reallocation scenario (Formula C).

    Args:
        baseline_results: Output from calculate_baseline_metrics.
        source_channel: The channel_medium to reduce spend on.
        target_channel: The channel_medium to increase spend on.
        shift_amount: Dollar amount to shift.

    Returns:
        Dict with before/after comparison and net impact.
    """
    source = next((r for r in baseline_results if r["channel_medium"] == source_channel), None)
    target = next((r for r in baseline_results if r["channel_medium"] == target_channel), None)

    if not source or not target:
        return {"error": f"Channel not found. Available: {[r['channel_medium'] for r in baseline_results]}"}

    # Before
    old_spend_s = source["spend"]
    old_rev_s = source["revenue"]
    old_roas_s = source["roas"]
    old_spend_t = target["spend"]
    old_rev_t = target["revenue"]
    old_roas_t = target["roas"]

    # After
    new_spend_s = old_spend_s - shift_amount
    new_rev_s = new_spend_s * old_roas_s if new_spend_s > 0 else 0.0
    new_spend_t = old_spend_t + shift_amount
    new_rev_t = new_spend_t * old_roas_t

    # System impact
    old_combined_rev = old_rev_s + old_rev_t
    new_combined_rev = new_rev_s + new_rev_t
    net_delta = new_combined_rev - old_combined_rev
    new_combined_roas = safe_divide(new_combined_rev, new_spend_s + new_spend_t)

    return {
        "source_channel": source_channel,
        "target_channel": target_channel,
        "shift_amount": shift_amount,
        "before": {
            source_channel: {"spend": round(old_spend_s, 2), "revenue": round(old_rev_s, 2), "roas": old_roas_s},
            target_channel: {"spend": round(old_spend_t, 2), "revenue": round(old_rev_t, 2), "roas": old_roas_t},
            "combined_revenue": round(old_combined_rev, 2),
        },
        "after": {
            source_channel: {"spend": round(new_spend_s, 2), "revenue": round(new_rev_s, 2)},
            target_channel: {"spend": round(new_spend_t, 2), "revenue": round(new_rev_t, 2)},
            "combined_revenue": round(new_combined_rev, 2),
            "combined_roas": round(new_combined_roas, 2),
        },
        "net_revenue_delta": round(net_delta, 2),
    }


def format_baseline_table(results: list[dict]) -> str:
    """Formats baseline metrics as a readable Markdown-style table string."""
    header = (
        f"{'Channel':<12} {'Sessions':>10} {'Purchases':>10} {'Revenue':>12} "
        f"{'Spend':>10} {'CVR%':>8} {'ROAS':>8} {'CPA':>10} "
        f"{'Gross Profit':>14} {'Contrib Margin':>16} "
        f"{'RPC':>8} {'CPC':>8} {'Net Unit':>10} {'Alert':>6}"
    )
    separator = "-" * len(header)
    lines = [header, separator]

    for r in results:
        alert_flag = "[!!]" if r["roas_alert"] else "[OK]"
        line = (
            f"{r['channel_medium']:<12} {r['sessions']:>10} {r['purchases']:>10} "
            f"${r['revenue']:>11,.2f} ${r['spend']:>9,.2f} "
            f"{r['cvr_pct']:>7.2f}% {r['roas']:>7.2f}x ${r['cpa']:>9,.2f} "
            f"${r['gross_profit']:>13,.2f} ${r['contribution_margin']:>15,.2f} "
            f"${r['rpc']:>7.4f} ${r['cpc']:>7.4f} ${r['net_unit_profit']:>9.4f} {alert_flag:>6}"
        )
        lines.append(line)

    return "\n".join(lines)


def format_reallocation_report(result: dict) -> str:
    """Formats a reallocation scenario result as a readable report."""
    if "error" in result:
        return f"Error: {result['error']}"

    src = result["source_channel"]
    tgt = result["target_channel"]
    before = result["before"]
    after = result["after"]

    report = [
        f"\n{'='*60}",
        f" BUDGET REALLOCATION SCENARIO",
        f"{'='*60}",
        f" Shift: ${result['shift_amount']:,.2f} from '{src}' → '{tgt}'",
        f"{'='*60}",
        f"",
        f" {'Metric':<20} {'Before':>14} {'After':>14} {'Delta':>14}",
        f" {'-'*62}",
        f" {src + ' Spend':<20} ${before[src]['spend']:>13,.2f} ${after[src]['spend']:>13,.2f}",
        f" {src + ' Revenue':<20} ${before[src]['revenue']:>13,.2f} ${after[src]['revenue']:>13,.2f}",
        f" {tgt + ' Spend':<20} ${before[tgt]['spend']:>13,.2f} ${after[tgt]['spend']:>13,.2f}",
        f" {tgt + ' Revenue':<20} ${before[tgt]['revenue']:>13,.2f} ${after[tgt]['revenue']:>13,.2f}",
        f" {'-'*62}",
        f" {'Combined Revenue':<20} ${before['combined_revenue']:>13,.2f} ${after['combined_revenue']:>13,.2f} ${result['net_revenue_delta']:>13,.2f}",
        f" {'Combined ROAS':<20} {'':>14} {after['combined_roas']:>13.2f}x",
        f"{'='*60}",
    ]

    if result["net_revenue_delta"] > 0:
        report.append(f" [OK] Net Impact: +${result['net_revenue_delta']:,.2f} revenue increase")
    elif result["net_revenue_delta"] < 0:
        report.append(f" [!!] Net Impact: -${abs(result['net_revenue_delta']):,.2f} revenue decrease")
    else:
        report.append(f" [--] Net Impact: No change in revenue")

    report.append(f"{'='*60}\n")
    return "\n".join(report)
