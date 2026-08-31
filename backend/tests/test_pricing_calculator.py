import pytest

from app.models.base import SessionLocal
from app.pricing import (
    CostCalculationRequest,
    PricingModel,
    PricingNotFoundError,
    ServiceType,
    UsageMode,
    UsageSample,
    calculate_cost,
)
from app.pricing.seed_data import PROVIDER, seed_pricing


@pytest.fixture(scope="module", autouse=True)
def _ensure_seed_data():
    db = SessionLocal()
    try:
        seed_pricing(db)
    finally:
        db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_flat_on_demand_compute_cost(db) -> None:
    request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND,
        usage_mode=UsageMode.FLAT,
        quantity=100.0,
    )

    result = calculate_cost(request, db)

    assert result.resolved_quantity == 100.0
    assert result.cost == pytest.approx(100.0 * 0.096, rel=1e-6)
    assert result.currency == "USD"
    assert len(result.tiers_applied) == 1


def test_reserved_is_cheaper_than_on_demand(db) -> None:
    on_demand_request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.ON_DEMAND,
        quantity=1000.0,
    )
    reserved_request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        pricing_model=PricingModel.RESERVED,
        commitment_term_months=12,
        quantity=1000.0,
    )

    on_demand_cost = calculate_cost(on_demand_request, db).cost
    reserved_cost = calculate_cost(reserved_request, db).cost

    assert reserved_cost < on_demand_cost


def test_longer_commitment_term_is_cheaper(db) -> None:
    def cost_for(term: int) -> float:
        request = CostCalculationRequest(
            provider=PROVIDER,
            region="us-east-1",
            service=ServiceType.DATABASE,
            sku="database-instance-hour",
            unit="hour",
            pricing_model=PricingModel.RESERVED,
            commitment_term_months=term,
            quantity=500.0,
        )
        return calculate_cost(request, db).cost

    assert cost_for(36) < cost_for(12)


def test_reserved_without_commitment_term_is_rejected() -> None:
    with pytest.raises(ValueError):
        CostCalculationRequest(
            provider=PROVIDER,
            region="us-east-1",
            service=ServiceType.COMPUTE,
            sku="compute-instance-hour",
            unit="hour",
            pricing_model=PricingModel.RESERVED,
            quantity=10.0,
        )


def test_missing_pricing_raises_not_found(db) -> None:
    request = CostCalculationRequest(
        provider="nonexistent-provider",
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        quantity=10.0,
    )

    with pytest.raises(PricingNotFoundError):
        calculate_cost(request, db)


def test_reserved_not_available_for_network_egress_raises(db) -> None:
    request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-network-egress",
        unit="gb",
        pricing_model=PricingModel.RESERVED,
        commitment_term_months=12,
        quantity=10.0,
    )

    with pytest.raises(PricingNotFoundError):
        calculate_cost(request, db)


def test_storage_tiering_applies_graduated_rates(db) -> None:
    # objstorage-storage tiers (us-east-1): [0,51200)=0.0000315, [51200,512000)=0.0000301, [512000,inf)=0.0000288
    small_request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.OBJECT_STORAGE,
        sku="objstorage-storage",
        unit="gb-hour",
        quantity=1000.0,
    )
    small_result = calculate_cost(small_request, db)
    assert len(small_result.tiers_applied) == 1
    assert small_result.cost == pytest.approx(1000.0 * 0.0000315, rel=1e-6)

    large_request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.OBJECT_STORAGE,
        sku="objstorage-storage",
        unit="gb-hour",
        quantity=600000.0,
    )
    large_result = calculate_cost(large_request, db)
    assert len(large_result.tiers_applied) == 3

    expected = (
        51200 * 0.0000315
        + (512000 - 51200) * 0.0000301
        + (600000 - 512000) * 0.0000288
    )
    assert large_result.cost == pytest.approx(expected, rel=1e-6)

    # Marginal (blended) rate for the large request must be lower than the
    # small request's flat rate, since more usage spilled into cheaper tiers.
    assert (large_result.cost / large_result.resolved_quantity) < (
        small_result.cost / small_result.resolved_quantity
    )


def test_autoscaling_usage_mode_time_weights_quantity(db) -> None:
    flat_equivalent = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        usage_mode=UsageMode.FLAT,
        quantity=15.0,  # 2*3 + 5*1 + 1*4 = 15 instance-hours
    )
    autoscaling_request = CostCalculationRequest(
        provider=PROVIDER,
        region="us-east-1",
        service=ServiceType.COMPUTE,
        sku="compute-instance-hour",
        unit="hour",
        usage_mode=UsageMode.AUTOSCALING,
        usage_series=[
            UsageSample(quantity=2, duration_hours=3),
            UsageSample(quantity=5, duration_hours=1),
            UsageSample(quantity=1, duration_hours=4),
        ],
    )

    flat_result = calculate_cost(flat_equivalent, db)
    autoscaling_result = calculate_cost(autoscaling_request, db)

    assert autoscaling_result.resolved_quantity == pytest.approx(15.0)
    assert autoscaling_result.cost == pytest.approx(flat_result.cost)


def test_autoscaling_requires_usage_series() -> None:
    with pytest.raises(ValueError):
        CostCalculationRequest(
            provider=PROVIDER,
            region="us-east-1",
            service=ServiceType.COMPUTE,
            sku="compute-instance-hour",
            unit="hour",
            usage_mode=UsageMode.AUTOSCALING,
        )


def test_regional_price_multiplier_applied(db) -> None:
    def cost_in(region: str) -> float:
        request = CostCalculationRequest(
            provider=PROVIDER,
            region=region,
            service=ServiceType.COMPUTE,
            sku="compute-instance-hour",
            unit="hour",
            quantity=100.0,
        )
        return calculate_cost(request, db).cost

    assert cost_in("eu-west-1") > cost_in("us-east-1")
    assert cost_in("ap-southeast-1") > cost_in("eu-west-1")


def test_invalid_quantity_rejected() -> None:
    with pytest.raises(ValueError):
        CostCalculationRequest(
            provider=PROVIDER,
            region="us-east-1",
            service=ServiceType.COMPUTE,
            sku="compute-instance-hour",
            unit="hour",
            quantity=-5.0,
        )
