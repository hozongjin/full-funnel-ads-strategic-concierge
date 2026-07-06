# /// script
# dependencies = [
#   "pyyaml",
# ]
# ///

"""
Config Loader — Reads and validates config/master_data.yaml.

This is the single entry point for all financial cost inputs used by the
CalculationAgent. All spend figures, CPC proxies, and margin rates come
from this file rather than being hardcoded.
"""

import os
import yaml


def _find_config_path() -> str:
    """Resolves the absolute path to config/master_data.yaml relative to the project root."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    return os.path.join(project_root, "config", "master_data.yaml")


def load_master_data() -> dict:
    """Loads and returns the full master_data.yaml as a dictionary.

    Raises FileNotFoundError if the config file is missing.
    """
    config_path = _find_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Master data config not found at: {config_path}\n"
            "Please create config/master_data.yaml with your financial inputs."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def get_channel_spend(master_data: dict) -> dict:
    """Returns the channel_spend_usd_monthly mapping."""
    return master_data.get("channel_spend_usd_monthly", {})


def get_channel_cpc(master_data: dict) -> dict:
    """Returns the channel_cpc_proxy_usd mapping."""
    return master_data.get("channel_cpc_proxy_usd", {})


def get_gross_margins(master_data: dict) -> dict:
    """Returns the gross_margin_by_category mapping."""
    return master_data.get("gross_margin_by_category", {})


def get_assumptions(master_data: dict) -> dict:
    """Returns the global assumptions dictionary."""
    return master_data.get("assumptions", {})


def get_spend_for_channel(master_data: dict, channel_medium: str, num_days: int) -> float:
    """Calculates the pro-rated spend for a channel over the given number of days.

    Uses the spend_input_method from assumptions:
    - "monthly_budget": (monthly_spend / 30) * num_days
    - "cpc_proxy": Returns 0.0 (caller must multiply by sessions externally)
    """
    assumptions = get_assumptions(master_data)
    method = assumptions.get("spend_input_method", "monthly_budget")

    if method == "monthly_budget":
        monthly_spend = get_channel_spend(master_data).get(channel_medium, 0.0)
        return (monthly_spend / 30.0) * num_days
    else:
        # CPC proxy method — caller is responsible for multiplying by sessions
        return 0.0


def get_margin_for_category(master_data: dict, category: str) -> float:
    """Returns the gross margin rate for a product category, falling back to default."""
    margins = get_gross_margins(master_data)
    return margins.get(category, margins.get("default", 0.40))


if __name__ == "__main__":
    # Quick test: load and print the config
    print("Loading master_data.yaml...")
    data = load_master_data()
    print(f"\nChannel Spend (Monthly): {get_channel_spend(data)}")
    print(f"Channel CPC Proxy:       {get_channel_cpc(data)}")
    print(f"Gross Margins:           {get_gross_margins(data)}")
    print(f"Assumptions:             {get_assumptions(data)}")
    print(f"\nPro-rated spend for 'cpc' over 31 days: ${get_spend_for_channel(data, 'cpc', 31):.2f}")
    print(f"Margin for 'Apparel': {get_margin_for_category(data, 'Apparel')}")
    print(f"Margin for 'Unknown': {get_margin_for_category(data, 'Unknown')} (fallback)")
    print("\n[OK] Config loaded successfully!")
