"""Badge computation for completed evaluations.

Badges are computed at write time when an eval completes and stored
as a JSONB array on the evaluation row.
"""

from typing import Any


def compute_badges(accuracy: float, categories: dict[str, Any]) -> list[str]:
    """Compute badges based on evaluation results.

    Args:
        accuracy: Overall accuracy (0.0 - 1.0).
        categories: Dict of {category_name: {accuracy, correct, total}}.

    Returns:
        List of badge strings.
    """
    badges: list[str] = []

    if accuracy >= 0.90:
        badges.append("excellence")

    if categories and all(
        cat.get("accuracy", 0) >= 0.80 for cat in categories.values()
    ):
        badges.append("balanced")

    if categories:
        for name, cat in categories.items():
            if cat.get("accuracy", 0) >= 0.95:
                badges.append(f"{name}-mastery")

    return badges
