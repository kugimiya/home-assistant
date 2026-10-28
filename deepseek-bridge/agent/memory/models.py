"""Memory records. Stdlib stand-in for the Pi pydantic models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConfidenceLevel = Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
FactSource = Literal["user_explicit", "model_inferred"]
_CONFIDENCE = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class ExtractedFact:
    fact: str
    confidence: str = "INFERRED"


@dataclass
class ExtractedTrait:
    trait: str
    value: str
    confidence: float = 0.9


@dataclass
class SessionSummaryResult:
    summary: str
    tags: list[str] = field(default_factory=list)
    importance: int = 50
    extracted_facts: list[ExtractedFact] = field(default_factory=list)
    traits: list[ExtractedTrait] = field(default_factory=list)

    @classmethod
    def model_validate(cls, data: object) -> SessionSummaryResult:
        if not isinstance(data, dict):
            raise ValueError("summary is not an object")
        summary = str(data.get("summary") or "").strip()
        if not summary:
            raise ValueError("empty summary")
        tags_raw = data.get("tags") or []
        tags = [str(tag) for tag in tags_raw] if isinstance(tags_raw, list) else []
        try:
            importance = int(data.get("importance", 50))
        except (TypeError, ValueError):
            importance = 50
        facts: list[ExtractedFact] = []
        for item in data.get("extracted_facts") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("fact") or "").strip()
            if not text:
                continue
            confidence = str(item.get("confidence") or "INFERRED")
            if confidence not in _CONFIDENCE:
                confidence = "INFERRED"
            facts.append(ExtractedFact(text, confidence))
        traits: list[ExtractedTrait] = []
        for item in data.get("traits") or []:
            if not isinstance(item, dict):
                continue
            trait = str(item.get("trait") or "").strip()
            value = str(item.get("value") or "").strip()
            if not trait or not value:
                continue
            try:
                confidence_value = float(item.get("confidence", 0.9))
            except (TypeError, ValueError):
                confidence_value = 0.9
            traits.append(ExtractedTrait(trait, value, _clamp(confidence_value, 0.0, 1.0)))
        return cls(summary, tags, int(_clamp(importance, 0, 100)), facts, traits)


@dataclass
class SearchHit:
    id: str
    channel: Literal["fact", "episode", "trait"]
    text: str
    score: float = 0.0
    created_at: str | None = None
    extra: dict[str, object] = field(default_factory=dict)
