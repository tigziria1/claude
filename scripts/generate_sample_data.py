"""Generate ``data/raw/sample_sales_data.csv``: a deliberately messy sales dataset.

The file mimics what a small tech company exports from several tools: mixed
date formats, currency symbols in numbers, inconsistent casing, placeholder
nulls, duplicated rows and a few extreme values. It is used to demo and test
the pipeline. Generation is deterministic (fixed seed).

Usage:
    python scripts/generate_sample_data.py [--rows 600] [--out data/raw/sample_sales_data.csv]
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("generate_sample_data")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PRODUCTS: dict[str, tuple[str, float, float]] = {
    # name: (category, unit price in EUR, relative popularity)
    "Premium Plan": ("Subscription", 1200.0, 0.22),
    "Starter Plan": ("Subscription", 290.0, 0.30),
    "Team Plan": ("Subscription", 650.0, 0.18),
    "Onboarding Pack": ("Services", 450.0, 0.12),
    "Custom Integration": ("Services", 2400.0, 0.06),
    "Analytics Add-on": ("Add-on", 180.0, 0.12),
}
REGIONS: dict[str, float] = {"Europe": 0.40, "North America": 0.35, "Asia Pacific": 0.15, "Middle East": 0.10}
CHANNELS: list[str] = ["Website", "Partner", "Direct Sales", "Mobile App"]
REPS: list[str] = ["Amira Benali", "Lucas Martin", "Sofia Rossi", "Kenji Sato", "Nadia Haddad", "Tom Becker"]
CUSTOMERS: list[str] = [
    "Atlas Logistics", "Brightwave", "Cedar Health", "Delta Retail", "Echo Media", "Futura Labs",
    "Granite Bank", "Helix Robotics", "Iris Studio", "Juniper Foods", "Kappa Energy", "Lumen Edu",
    "Mosaic Travel", "Nova Fintech", "Orbit Games", "Pixel Forge", "Quartz Legal", "Riverstone",
]

# Monthly demand multipliers: steady growth, an August dip, a strong Q4.
SEASONALITY: dict[int, float] = {1: 0.85, 2: 0.9, 3: 1.0, 4: 1.0, 5: 1.05, 6: 1.1,
                                 7: 1.0, 8: 0.7, 9: 1.1, 10: 1.2, 11: 1.35, 12: 1.45}


def _messy_date(d: date, rng: random.Random) -> str:
    """Render a date in one of several inconsistent formats (or leave it blank)."""
    roll = rng.random()
    if roll < 0.015:
        return ""
    if roll < 0.55:
        return d.isoformat()
    if roll < 0.75:
        return d.strftime("%Y/%m/%d")
    if roll < 0.9:
        return d.strftime("%b %d %Y")
    return d.strftime("%d-%b-%Y")


def _messy_money(value: float, rng: random.Random) -> str:
    """Render an amount with inconsistent currency formatting."""
    roll = rng.random()
    if roll < 0.4:
        return f"{value:.2f}"
    if roll < 0.65:
        return f"€{value:,.2f}"
    if roll < 0.85:
        return f"{value:.2f} EUR"
    return f"  {value:.0f} "


def _messy_text(value: str, rng: random.Random) -> str:
    """Randomly change casing / add stray whitespace to a label."""
    roll = rng.random()
    if roll < 0.08:
        return value.upper()
    if roll < 0.16:
        return value.lower()
    if roll < 0.24:
        return f" {value}  "
    return value


def _maybe_null(value: str, rng: random.Random, rate: float) -> str:
    """Replace a value by one of the null placeholders seen in real exports."""
    if rng.random() < rate:
        return rng.choice(["", "N/A", "null", "-"])
    return value


def generate(rows: int, seed: int = 42) -> list[dict[str, str]]:
    """Build the list of messy records.

    Args:
        rows: Number of distinct orders before duplicates are injected.
        seed: Random seed for reproducibility.

    Returns:
        A list of CSV row dictionaries.
    """
    rng = random.Random(seed)
    start = date(2025, 1, 1)
    days = [start + timedelta(days=i) for i in range(365)]
    day_weights = [SEASONALITY[d.month] * (1 + 0.35 * i / 365) for i, d in enumerate(days)]

    product_names = list(PRODUCTS)
    product_weights = [PRODUCTS[p][2] for p in product_names]
    region_names = list(REGIONS)

    records: list[dict[str, str]] = []
    for i in range(rows):
        order_date = rng.choices(days, weights=day_weights)[0]
        product = rng.choices(product_names, weights=product_weights)[0]
        category, base_price, _ = PRODUCTS[product]

        # Europe grows faster through the year than the other regions.
        progress = (order_date - start).days / 365
        region_weights = [REGIONS[r] * (1 + (0.9 if r == "Europe" else 0.1) * progress) for r in region_names]
        region = rng.choices(region_names, weights=region_weights)[0]

        channel = rng.choices(CHANNELS, weights=[0.35, 0.15, 0.25, 0.25 + 0.2 * progress])[0]
        quantity = rng.choices([1, 2, 3, 4, 5, 10], weights=[0.45, 0.2, 0.12, 0.08, 0.1, 0.05])[0]
        unit_price = round(base_price * rng.uniform(0.9, 1.1), 2)
        revenue = round(quantity * unit_price, 2)

        if rng.random() < 0.012:  # data-entry errors: an extra zero
            revenue *= 10

        records.append({
            " Order ID": f"ORD-{10000 + i}",
            "order_date": _messy_date(order_date, rng),
            "Customer Name": _maybe_null(rng.choice(CUSTOMERS), rng, 0.02),
            "PRODUCT": _messy_text(product, rng),
            "Category": category,
            "Region": _maybe_null(_messy_text(region, rng), rng, 0.04),
            "Sales Rep": _maybe_null(rng.choice(REPS), rng, 0.05),
            "Channel": _messy_text(channel, rng),
            "Quantity": _maybe_null(str(quantity), rng, 0.03),
            "Unit Price": _maybe_null(_messy_money(unit_price, rng), rng, 0.02),
            "Revenue (EUR)": _maybe_null(_messy_money(revenue, rng), rng, 0.03),
        })

    # Inject exact duplicates (double exports / copy-paste errors).
    duplicates = rng.sample(records, k=max(1, rows // 30))
    records.extend(dict(r) for r in duplicates)
    rng.shuffle(records)
    return records


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=int, default=600, help="number of distinct orders (default: 600)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "raw" / "sample_sales_data.csv")
    args = parser.parse_args()

    records = generate(args.rows, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    logger.info("Wrote %d rows to %s", len(records), args.out)


if __name__ == "__main__":
    main()
