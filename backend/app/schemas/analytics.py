"""Aggregate analytics over the persisted claims, for the UI's Analytics dashboard.

Every claim is bucketed into one of five mutually-exclusive *segments* (used consistently
across the donut, the per-category stacked bars and the KPIs):

  approved | partial | rejected | review (auto MANUAL_REVIEW + HITL PENDING_REVIEW) | action
  (NEEDS_MEMBER_ACTION — a document the member must re-upload).
"""

from __future__ import annotations

from pydantic import BaseModel


class NameValue(BaseModel):
    name: str
    value: int


class CategoryStat(BaseModel):
    category: str
    approved: int = 0
    partial: int = 0
    rejected: int = 0
    review: int = 0
    action: int = 0
    total: int = 0


class TimePoint(BaseModel):
    date: str  # YYYY-MM-DD (IST calendar day, by created_at)
    claims: int
    approved_amount: int


class Bucket(BaseModel):
    bucket: str  # e.g. "80–100%"
    count: int


class Analytics(BaseModel):
    total_claims: int
    approved: int
    partial: int
    rejected: int
    review: int
    action: int
    approval_rate: float  # (approved + partial) / (approved + partial + rejected); 0 when none
    total_approved_amount: int
    avg_confidence: float | None
    degraded_count: int
    by_decision: list[NameValue]
    by_category: list[CategoryStat]
    over_time: list[TimePoint]
    confidence_buckets: list[Bucket]
