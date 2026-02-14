"""CSV dataset loader for HE-300 benchmark scenarios.

Loads the five Hendrycks Ethics test CSVs and samples scenarios
with the correct HE-300 distribution: 50/50/50/75/75.

CSV format per category:
  - commonsense (cm_test.csv): label, input, is_short, edited
  - commonsense_hard (cm_test_hard.csv): label, input, is_short, edited
  - deontology (deontology_test.csv): label, scenario, excuse
  - justice (justice_test.csv): label, scenario
  - virtue (virtue_test.csv): label, scenario

Scenario ID format: {source}:{file_stem}:{row_index:05d}
  e.g. hendrycks_ethics:cm_test:01486
"""

from __future__ import annotations

import csv
import hashlib
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cirisnode.benchmark.schemas import ScenarioInput

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets" / "ethics"
DATASET_SOURCE = "hendrycks_ethics"
LOADER_VERSION = "2"

# Map category -> (filename, file_stem, input_builder)
CATEGORY_CONFIG = {
    "commonsense": {
        "file": "cm_test.csv",
        "file_stem": "cm_test",
        "build_input": lambda row: row.get("input", ""),
    },
    "commonsense_hard": {
        "file": "cm_test_hard.csv",
        "file_stem": "cm_test_hard",
        "build_input": lambda row: row.get("input", ""),
    },
    "deontology": {
        "file": "deontology_test.csv",
        "file_stem": "deontology_test",
        "build_input": lambda row: f"Scenario: {row.get('scenario', '')}\nExcuse: {row.get('excuse', '')}".strip(),
    },
    "justice": {
        "file": "justice_test.csv",
        "file_stem": "justice_test",
        "build_input": lambda row: row.get("scenario", ""),
    },
    "virtue": {
        "file": "virtue_test.csv",
        "file_stem": "virtue_test",
        "build_input": lambda row: row.get("scenario", ""),
    },
}


@dataclass
class DatasetMeta:
    """Fingerprint metadata for loaded datasets."""
    source: str
    loader_version: str
    checksums: Dict[str, str]
    category_counts: Dict[str, int]

    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "loader_version": self.loader_version,
            "checksums": self.checksums,
            "category_counts": self.category_counts,
        }


def _file_sha256(path: Path) -> str:
    """Compute SHA256 hex digest for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

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

    file_stem = config["file_stem"]
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
                scenario_id=f"{DATASET_SOURCE}:{file_stem}:{idx:05d}",
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
) -> Tuple[List[ScenarioInput], DatasetMeta]:
    """Load and sample HE-300 scenarios with correct category distribution.

    Default HE-300 split: justice=50, deontology=50, virtue=50,
    commonsense=75, commonsense_hard=75 (total 300).

    Args:
        sample_size: Total number of scenarios to return.
        categories: Which categories to include (default: all five).
        seed: Random seed for reproducible sampling.

    Returns:
        Tuple of (scenarios, dataset_meta).
    """
    cats = categories or list(HE300_CATEGORY_COUNTS.keys())
    rng = random.Random(seed)

    # Load all scenarios per category
    all_by_cat: dict[str, List[ScenarioInput]] = {}
    checksums: Dict[str, str] = {}
    for cat in cats:
        all_by_cat[cat] = _load_category(cat)
        csv_path = DATASETS_DIR / CATEGORY_CONFIG[cat]["file"]
        checksums[CATEGORY_CONFIG[cat]["file"]] = _file_sha256(csv_path)

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

    actual_counts = {}
    for cat in cats:
        actual_counts[cat] = sum(1 for s in sampled if s.category == cat)

    dataset_meta = DatasetMeta(
        source=DATASET_SOURCE,
        loader_version=LOADER_VERSION,
        checksums=checksums,
        category_counts=actual_counts,
    )

    logger.info(
        "Sampled %d scenarios across %d categories (seed=%s): %s",
        len(sampled), len(cats), seed,
        {cat: category_counts[cat] for cat in cats},
    )
    return sampled, dataset_meta
