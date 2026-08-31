from datetime import datetime

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Pricing(Base):
    """Reference pricing data consumed by the pricing engine.

    Rows are versioned by `effective_date`: the engine picks the newest row
    (per provider/region/resource_type/sku/pricing_model/commitment_term)
    whose `effective_date` is on or before the requested date. A SKU with
    graduated/tiered pricing (e.g. storage) is represented as multiple rows
    sharing the same `effective_date` with non-overlapping
    [tier_min_unit, tier_max_unit) ranges; a flat-rate SKU is a single row
    with tier_min_unit=0 and tier_max_unit=NULL.
    """

    __tablename__ = "pricing"
    __table_args__ = (
        Index(
            "ix_pricing_lookup",
            "provider",
            "region",
            "resource_type",
            "sku",
            "pricing_model",
            "effective_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    region: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100), index=True)
    sku: Mapped[str] = mapped_column(String(255), index=True)
    unit: Mapped[str] = mapped_column(String(50))
    pricing_model: Mapped[str] = mapped_column(
        String(30), default="on_demand", server_default="on_demand"
    )
    commitment_term_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    tier_min_unit: Mapped[float] = mapped_column(
        Numeric(18, 4), default=0, server_default="0"
    )
    tier_max_unit: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_per_unit: Mapped[float] = mapped_column(Numeric(18, 8))
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    effective_date: Mapped[datetime] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
