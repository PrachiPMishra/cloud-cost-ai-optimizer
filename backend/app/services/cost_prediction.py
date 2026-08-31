"""Combines Phase 4 (forecasting) and Phase 3 (pricing) into a predicted
next-period bill: for each (resource, usage_type) in scope, forecast the
usage over the requested horizon, price the forecast's point estimate and
its lower/upper bounds through the same pricing engine, and aggregate.

Uncertainty is propagated by re-running the (possibly tiered, non-linear)
pricing calculation at the lower-bound and upper-bound quantities rather
than just scaling the point cost — correct even when a forecast crosses a
pricing tier boundary. Per-day usage bounds are summed (not combined via
sqrt-sum-of-squares) to get a horizon-total bound: cloud usage is
autocorrelated within a billing period (a busy day tends to be followed by
another busy day), so treating daily errors as independent would
understate the total uncertainty.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.forecasting.data import NoHistoricalDataError, load_daily_series
from app.forecasting.engine import InsufficientHistoryError, run_forecast
from app.forecasting.enums import ForecastHorizon
from app.models.cost_prediction import CostPrediction
from app.models.forecast import Forecast
from app.models.resource import Resource
from app.pricing.calculator import PricingNotFoundError, calculate_cost
from app.pricing.enums import PricingModel, ServiceType
from app.pricing.schemas import CostCalculationRequest
from app.pricing.aggregation import (
    aggregate_by_resource,
    aggregate_by_service,
    aggregate_by_usage_unit,
    aggregate_total,
)
from app.pricing.skus import SKU_CATALOG

BILL_TARGET_METRIC = "cost"


class NoResourcesInScopeError(Exception):
    pass


class NoForecastableLineItemsError(Exception):
    pass


class BillNotFoundError(Exception):
    pass


class LineItemBreakdown(BaseModel):
    resource_id: str
    service: str
    usage_type: str
    sku: str
    unit: str
    forecast_model: str
    predicted_quantity: float
    predicted_cost: float
    lower_bound_cost: float | None
    upper_bound_cost: float | None


class CostPredictionSummary(BaseModel):
    forecast_id: int
    provider: str
    pricing_model: PricingModel
    horizon_days: int
    period_start: date
    period_end: date
    generated_at: datetime
    total_cost: float
    total_lower_bound: float | None
    total_upper_bound: float | None
    by_service: dict[str, float]
    by_resource: dict[str, float]
    by_usage_unit: dict[str, float]
    line_items: list[LineItemBreakdown]
    skipped: list[str]


def _resolve_resources(
    db: Session,
    provider: str,
    resource_external_id: str | None,
    service: ServiceType | None,
) -> list[Resource]:
    if resource_external_id:
        resource = (
            db.query(Resource).filter(Resource.external_id == resource_external_id).first()
        )
        if resource is None:
            raise NoResourcesInScopeError(
                f"No resource with external_id={resource_external_id!r}"
            )
        return [resource]

    query = db.query(Resource).filter(Resource.provider == provider)
    if service is not None:
        query = query.filter(Resource.resource_type == service.value)
    return query.all()


def predict_bill(
    db: Session,
    *,
    provider: str,
    horizon: ForecastHorizon,
    pricing_model: PricingModel = PricingModel.ON_DEMAND,
    commitment_term_months: int | None = None,
    resource_external_id: str | None = None,
    service: ServiceType | None = None,
) -> CostPredictionSummary:
    resources = _resolve_resources(db, provider, resource_external_id, service)
    if not resources:
        raise NoResourcesInScopeError(
            f"No resources found for provider={provider!r}"
            + (f" service={service.value!r}" if service else "")
        )

    line_items: list[LineItemBreakdown] = []
    point_results = []
    skipped: list[str] = []
    training_starts: list[date] = []
    training_ends: list[date] = []
    period_start: date | None = None
    period_end: date | None = None

    for resource in resources:
        try:
            service_enum = ServiceType(resource.resource_type)
        except ValueError:
            skipped.append(
                f"{resource.external_id}: unsupported resource_type "
                f"{resource.resource_type!r}"
            )
            continue

        for usage_type, (sku, unit) in SKU_CATALOG.get(service_enum, {}).items():
            try:
                series = load_daily_series(db, resource, usage_type)
            except NoHistoricalDataError as exc:
                skipped.append(f"{resource.external_id}/{usage_type}: {exc}")
                continue

            try:
                forecast_result = run_forecast(
                    series, resource.external_id, usage_type, horizon
                )
            except InsufficientHistoryError as exc:
                skipped.append(f"{resource.external_id}/{usage_type}: {exc}")
                continue

            total_point = sum(p.predicted_usage for p in forecast_result.points)
            bounds_known = all(
                p.lower_bound is not None and p.upper_bound is not None
                for p in forecast_result.points
            )
            total_lower = (
                sum(p.lower_bound for p in forecast_result.points) if bounds_known else None
            )
            total_upper = (
                sum(p.upper_bound for p in forecast_result.points) if bounds_known else None
            )

            try:
                point_result = calculate_cost(
                    CostCalculationRequest(
                        provider=provider,
                        region=resource.region,
                        service=service_enum,
                        sku=sku,
                        unit=unit,
                        pricing_model=pricing_model,
                        commitment_term_months=commitment_term_months,
                        quantity=total_point,
                        resource_id=resource.external_id,
                    ),
                    db,
                )
            except PricingNotFoundError as exc:
                skipped.append(str(exc))
                continue

            lower_cost = upper_cost = None
            if total_lower is not None:
                lower_cost = calculate_cost(
                    CostCalculationRequest(
                        provider=provider,
                        region=resource.region,
                        service=service_enum,
                        sku=sku,
                        unit=unit,
                        pricing_model=pricing_model,
                        commitment_term_months=commitment_term_months,
                        quantity=total_lower,
                        resource_id=resource.external_id,
                    ),
                    db,
                ).cost
            if total_upper is not None:
                upper_cost = calculate_cost(
                    CostCalculationRequest(
                        provider=provider,
                        region=resource.region,
                        service=service_enum,
                        sku=sku,
                        unit=unit,
                        pricing_model=pricing_model,
                        commitment_term_months=commitment_term_months,
                        quantity=total_upper,
                        resource_id=resource.external_id,
                    ),
                    db,
                ).cost

            point_results.append(point_result)
            line_items.append(
                LineItemBreakdown(
                    resource_id=resource.external_id,
                    service=service_enum.value,
                    usage_type=usage_type,
                    sku=sku,
                    unit=unit,
                    forecast_model=forecast_result.chosen_model_name,
                    predicted_quantity=total_point,
                    predicted_cost=point_result.cost,
                    lower_bound_cost=lower_cost,
                    upper_bound_cost=upper_cost,
                )
            )

            training_starts.append(forecast_result.training_window_start)
            training_ends.append(forecast_result.training_window_end)
            p_start, p_end = forecast_result.points[0].date, forecast_result.points[-1].date
            period_start = p_start if period_start is None else min(period_start, p_start)
            period_end = p_end if period_end is None else max(period_end, p_end)

    if not line_items:
        raise NoForecastableLineItemsError(
            "No (resource, usage_type) in scope produced a usable forecast: "
            + "; ".join(skipped[:10])
        )

    total_cost = aggregate_total(point_results)
    by_service = aggregate_by_service(point_results)
    by_resource = aggregate_by_resource(point_results)
    by_usage_unit = aggregate_by_usage_unit(point_results)

    total_lower_bound = (
        sum(li.lower_bound_cost for li in line_items)
        if all(li.lower_bound_cost is not None for li in line_items)
        else None
    )
    total_upper_bound = (
        sum(li.upper_bound_cost for li in line_items)
        if all(li.upper_bound_cost is not None for li in line_items)
        else None
    )

    forecast_row = Forecast(
        resource_id=None,
        model_name="bill_prediction",
        model_version="1.0",
        target_metric=BILL_TARGET_METRIC,
        horizon_days=horizon.days,
        training_window_start=datetime.combine(
            min(training_starts), time.min, tzinfo=timezone.utc
        ),
        training_window_end=datetime.combine(
            max(training_ends), time.min, tzinfo=timezone.utc
        ),
        status="completed",
        run_metadata={
            "provider": provider,
            "pricing_model": pricing_model.value,
            "commitment_term_months": commitment_term_months,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_cost": total_cost,
            "total_lower_bound": total_lower_bound,
            "total_upper_bound": total_upper_bound,
            "by_service": by_service,
            "by_resource": by_resource,
            "by_usage_unit": by_usage_unit,
            "line_item_models": {
                f"{li.resource_id}:{li.usage_type}": li.forecast_model for li in line_items
            },
            "skipped": skipped[:50],
        },
    )
    db.add(forecast_row)
    db.flush()

    resource_by_external_id = {r.external_id: r for r in resources}
    prediction_rows = [
        CostPrediction(
            forecast_id=forecast_row.id,
            resource_id=resource_by_external_id[li.resource_id].id,
            usage_type=li.usage_type,
            sku=li.sku,
            predicted_date=period_end,
            predicted_usage=li.predicted_quantity,
            predicted_cost=li.predicted_cost,
            lower_bound=li.lower_bound_cost,
            upper_bound=li.upper_bound_cost,
        )
        for li in line_items
    ]
    db.add_all(prediction_rows)
    db.commit()
    db.refresh(forecast_row)

    return CostPredictionSummary(
        forecast_id=forecast_row.id,
        provider=provider,
        pricing_model=pricing_model,
        horizon_days=horizon.days,
        period_start=period_start,
        period_end=period_end,
        generated_at=forecast_row.generated_at,
        total_cost=total_cost,
        total_lower_bound=total_lower_bound,
        total_upper_bound=total_upper_bound,
        by_service=by_service,
        by_resource=by_resource,
        by_usage_unit=by_usage_unit,
        line_items=line_items,
        skipped=skipped,
    )


def get_stored_breakdown(
    db: Session, forecast_id: int | None = None
) -> CostPredictionSummary:
    if forecast_id is not None:
        forecast_row = db.get(Forecast, forecast_id)
        if forecast_row is None or forecast_row.target_metric != BILL_TARGET_METRIC:
            raise BillNotFoundError(f"No cost prediction with id={forecast_id}")
    else:
        forecast_row = (
            db.query(Forecast)
            .filter(Forecast.target_metric == BILL_TARGET_METRIC)
            .order_by(Forecast.generated_at.desc())
            .first()
        )
        if forecast_row is None:
            raise BillNotFoundError("No cost predictions have been generated yet")

    rows = (
        db.query(CostPrediction, Resource)
        .join(Resource, CostPrediction.resource_id == Resource.id)
        .filter(CostPrediction.forecast_id == forecast_row.id)
        .all()
    )

    metadata = forecast_row.run_metadata or {}
    line_item_models = metadata.get("line_item_models", {})

    line_items = []
    for prediction, resource in rows:
        try:
            service_enum = ServiceType(resource.resource_type)
            unit = SKU_CATALOG.get(service_enum, {}).get(prediction.usage_type, (None, "unknown"))[1]
        except ValueError:
            unit = "unknown"

        line_items.append(
            LineItemBreakdown(
                resource_id=resource.external_id,
                service=resource.resource_type,
                usage_type=prediction.usage_type or "unknown",
                sku=prediction.sku or "unknown",
                unit=unit,
                forecast_model=line_item_models.get(
                    f"{resource.external_id}:{prediction.usage_type}", "unknown"
                ),
                predicted_quantity=prediction.predicted_usage,
                predicted_cost=float(prediction.predicted_cost),
                lower_bound_cost=float(prediction.lower_bound)
                if prediction.lower_bound is not None
                else None,
                upper_bound_cost=float(prediction.upper_bound)
                if prediction.upper_bound is not None
                else None,
            )
        )

    return CostPredictionSummary(
        forecast_id=forecast_row.id,
        provider=metadata.get("provider", ""),
        pricing_model=PricingModel(metadata.get("pricing_model", PricingModel.ON_DEMAND.value)),
        horizon_days=forecast_row.horizon_days,
        period_start=date.fromisoformat(metadata["period_start"]),
        period_end=date.fromisoformat(metadata["period_end"]),
        generated_at=forecast_row.generated_at,
        total_cost=metadata.get("total_cost", 0.0),
        total_lower_bound=metadata.get("total_lower_bound"),
        total_upper_bound=metadata.get("total_upper_bound"),
        by_service=metadata.get("by_service", {}),
        by_resource=metadata.get("by_resource", {}),
        by_usage_unit=metadata.get("by_usage_unit", {}),
        line_items=line_items,
        skipped=metadata.get("skipped", []),
    )
