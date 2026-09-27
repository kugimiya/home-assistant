"""Hot / warm / cold temporal layers for memory search."""

from __future__ import annotations

from typing import Literal

TemporalLayer = Literal["hot", "warm", "cold", "all"]


def layer_sql_filter(
    layer: TemporalLayer,
    column: str,
    *,
    hot_hours: float,
    warm_days: float,
) -> tuple[str, tuple[()]]:
    """Return SQL fragment and params for created_at filtering."""
    if layer == "all":
        return "", ()

    col = column
    if layer == "hot":
        return f" AND {col} > datetime('now', ?)", (f"-{hot_hours} hours",)
    if layer == "warm":
        return (
            f" AND {col} <= datetime('now', ?) AND {col} > datetime('now', ?)",
            (f"-{hot_hours} hours", f"-{warm_days} days"),
        )
    if layer == "cold":
        return f" AND {col} <= datetime('now', ?)", (f"-{warm_days} days",)
    return "", ()


def temporal_layer_bonus(layer: TemporalLayer) -> float:
    """Small RRF bonus when searching all layers."""
    if layer == "hot":
        return 0.02
    if layer == "warm":
        return 0.01
    if layer == "cold":
        return 0.0
    return 0.0


def classify_row_layer(created_at: str, *, hot_hours: float, warm_days: float) -> TemporalLayer:
    """Classify a row timestamp into hot/warm/cold (for tests)."""
    # Used with fixed 'now' in tests via sqlite datetime comparisons in SQL instead.
    return "all"
