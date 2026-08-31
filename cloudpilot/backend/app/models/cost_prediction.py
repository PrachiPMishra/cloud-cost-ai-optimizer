from datetime import datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CostPrediction(Base):
    """A single predicted data point belonging to a forecast run.

    A usage forecast (Phase 4, `forecasts.target_metric` names the single
    metric) needs no further tag here. A bill/cost forecast
    (`forecasts.target_metric == "cost"`) spans multiple (resource,
    usage_type) line items per run, so each such row records its own
    `usage_type`/`sku` to stay unambiguous — both are NULL for a plain
    usage-forecast row, where the parent Forecast row already says what's
    being predicted.
    """

    __tablename__ = "cost_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    forecast_id: Mapped[int] = mapped_column(
        ForeignKey("forecasts.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    usage_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    predicted_date: Mapped[datetime] = mapped_column(Date, index=True)
    predicted_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_cost: Mapped[float | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    lower_bound: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)

    # Populated later, once predicted_date has passed and real usage_records
    # exist for it — closes the loop between a forecast and what happened.
    actual_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
