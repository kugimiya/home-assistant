"""Pydantic schemas for memory records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]
FactSource = Literal["user_explicit", "model_inferred"]


class ExtractedFact(BaseModel):
    fact: str
    confidence: ConfidenceLevel = "INFERRED"


class ExtractedTrait(BaseModel):
    trait: str
    value: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class SessionSummaryResult(BaseModel):
    summary: str
    tags: list[str] = Field(default_factory=list)
    importance: int = Field(default=50, ge=0, le=100)
    extracted_facts: list[ExtractedFact] = Field(default_factory=list)
    traits: list[ExtractedTrait] = Field(default_factory=list)


class SearchHit(BaseModel):
    id: str
    channel: Literal["fact", "episode", "trait"]
    text: str
    score: float = 0.0
    created_at: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)
