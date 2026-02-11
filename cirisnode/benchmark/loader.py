"""CSV dataset loader for HE-300 benchmark scenarios.

Loads the five Hendrycks Ethics test CSVs and samples scenarios
with the correct HE-300 distribution: 50/50/50/75/75.

CSV format per category:
  - commonsense (cm_test.csv): label, input, is_short, edited
  - commonsense_hard (cm_test_hard.csv): label, input, is_short, edited
  - deontology (deontology_test.csv): label, scenario, excuse
  - justice (justice_test.csv): label, scenario
  - virtue (virtue_test.csv): label, scenario
"""

from __future__ import annotations

import csv
import logging
import random
from pathlib import Path
from typing import List, Optional

from cirisnode.benchmark.schemas import ScenarioInput

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets" / "ethics"

# Map category -> (filename, input_builder)
CATEGORY_CONFIG = {
    "commonsense": {
        "file": "cm_test.csv",
        "build_input": lambda row: row.get("input", ""),
    },
    "commonsense_hard": {
        "file": "cm_test_hard.csv",
        "build_input": lambda row: row.get("input", ""),
    },
    "deontology": {
        "file": "deontology_test.csv",
        "build_input": lambda row: f"{row.get('scenario', '')} {row.get('excuse', '')}".strip(),
    },
    "justice": {
        "file": "justice_test.csv",
        "build_input": lambda row: row.get("scenario", ""),
    },
    "virtue": {
        "file": "virtue_test.csv",
        "build_input": lambda row: row.get("scenario", ""),
    },
}

# HE-300 category distribution: 50/50/50/75/75 = 300
HE300_CATEGORY_COUNTS = {
    "justice": 50,
    "deontology": 50,
    "virtue": 50,
    "commonsense": 75,
    "commonsense_hard": 75,
}


def _load_category(category: str) -> List[ScenarioInput]:
    """Load all scenarios for a single category from CSV."""
    config = CATEGORY_CONFIG.get(category)
    if not config:
        raise ValueError(f"Unknown category: {category!r}. Available: {list(CATEGORY_CONFIG)}")

    csv_path = DATASETS_DIR / config["file"]
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {csv_path}")

    scenarios: List[ScenarioInput] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            label_str = row.get("label", "").strip()
            if label_str not in ("0", "1"):
                continue
            label = int(label_str)
            input_text = config["build_input"](row)
            if not input_text.strip():
                continue
            scenarios.append(ScenarioInput(
                scenario_id=f"{category}-{idx:05d}",
                category=category,
                input_text=input_text,
                expected_label=label,
            ))

    logger.info("Loaded %d scenarios from %s", len(scenarios), csv_path.name)
    return scenarios


def load_scenarios(
    sample_size: int = 300,
    categories: Optional[List[str]] = None,
    seed: Optional[int] = None,
) -> List[ScenarioInput]:
    """Load and sample HE-300 scenarios with correct category distribution.

    Default HE-300 split: justice=50, deontology=50, virtue=50,
    commonsense=75, commonsense_hard=75 (total 300).

    Args:
        sample_size: Total number of scenarios to return.
        categories: Which categories to include (default: all five).
        seed: Random seed for reproducible sampling.

    Returns:
        List of ScenarioInput with correct per-category counts.
    """
    cats = categories or list(HE300_CATEGORY_COUNTS.keys())
    rng = random.Random(seed)

    # Load all scenarios per category
    all_by_cat: dict[str, List[ScenarioInput]] = {}
    for cat in cats:
        all_by_cat[cat] = _load_category(cat)

    # Use HE-300 distribution if sample_size == 300 and using default categories
    if sample_size == 300 and categories is None:
        category_counts = HE300_CATEGORY_COUNTS
    else:
        # Fallback: divide equally
        per_cat = sample_size // len(cats)
        remainder = sample_size % len(cats)
        category_counts = {}
        for i, cat in enumerate(cats):
            category_counts[cat] = per_cat + (1 if i < remainder else 0)

    sampled: List[ScenarioInput] = []
    for cat in cats:
        n = category_counts[cat]
        pool = all_by_cat[cat]
        if n >= len(pool):
            sampled.extend(pool)
        else:
            sampled.extend(rng.sample(pool, n))

    rng.shuffle(sampled)
    logger.info(
        "Sampled %d scenarios across %d categories (seed=%s): %s",
        len(sampled), len(cats), seed,
        {cat: category_counts[cat] for cat in cats},
    )
    return sampled
