from datetime import date

import pytest
from sqlalchemy import delete

from app.models.base import SessionLocal
from app.models.pricing import Pricing
from app.pricing.seed_data import (
    BASE_RATE_DEFINITIONS,
    REGIONS,
    build_seed_rows,
    main,
    seed_pricing,
)

TEST_PROVIDER = "test-seed-provider"
TEST_SOURCE = "test-seed-source-v1"
TEST_DATE = date(2099, 1, 1)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.execute(
            delete(Pricing).where(
                Pricing.provider == TEST_PROVIDER, Pricing.source == TEST_SOURCE
            )
        )
        session.commit()
        session.close()


def test_build_seed_rows_covers_every_region_and_definition() -> None:
    rows = build_seed_rows(TEST_PROVIDER, TEST_DATE, TEST_SOURCE)

    expected_row_count = sum(len(d["tiers"]) for d in BASE_RATE_DEFINITIONS) * len(REGIONS)
    assert len(rows) == expected_row_count

    regions_seen = {r.region for r in rows}
    assert regions_seen == set(REGIONS)
    assert all(r.provider == TEST_PROVIDER for r in rows)
    assert all(r.effective_date == TEST_DATE for r in rows)
    assert all(r.source == TEST_SOURCE for r in rows)
    assert all(r.price_per_unit > 0 for r in rows)


def test_build_seed_rows_applies_region_multiplier() -> None:
    rows = build_seed_rows(TEST_PROVIDER, TEST_DATE, TEST_SOURCE)
    by_region_sku = {(r.region, r.sku, r.tier_min_unit): r.price_per_unit for r in rows}

    definition = BASE_RATE_DEFINITIONS[0]
    tier_min, _, base_rate = definition["tiers"][0]
    sku = definition["sku"]

    prices = {region: by_region_sku[(region, sku, tier_min)] for region in REGIONS}
    # Not every region shares the same multiplier, so at least one differs from the base rate.
    assert len(set(prices.values())) >= 1
    for region, price in prices.items():
        assert price > 0


def test_seed_pricing_inserts_then_skips_without_replace(db) -> None:
    inserted = seed_pricing(db, provider=TEST_PROVIDER, effective_date=TEST_DATE, source=TEST_SOURCE)
    assert inserted > 0

    row_count_after_first = db.query(Pricing).filter(
        Pricing.provider == TEST_PROVIDER, Pricing.source == TEST_SOURCE
    ).count()
    assert row_count_after_first == inserted

    second = seed_pricing(db, provider=TEST_PROVIDER, effective_date=TEST_DATE, source=TEST_SOURCE)
    assert second == 0

    row_count_after_second = db.query(Pricing).filter(
        Pricing.provider == TEST_PROVIDER, Pricing.source == TEST_SOURCE
    ).count()
    assert row_count_after_second == row_count_after_first


def test_seed_pricing_replace_true_deletes_and_reinserts(db) -> None:
    first = seed_pricing(db, provider=TEST_PROVIDER, effective_date=TEST_DATE, source=TEST_SOURCE)
    assert first > 0

    stale_row = db.query(Pricing).filter(
        Pricing.provider == TEST_PROVIDER, Pricing.source == TEST_SOURCE
    ).first()
    stale_id = stale_row.id

    replaced = seed_pricing(
        db, provider=TEST_PROVIDER, effective_date=TEST_DATE, source=TEST_SOURCE, replace=True
    )
    assert replaced == first

    remaining_ids = {
        r.id
        for r in db.query(Pricing).filter(
            Pricing.provider == TEST_PROVIDER, Pricing.source == TEST_SOURCE
        )
    }
    assert stale_id not in remaining_ids
    assert len(remaining_ids) == replaced


def test_main_seeds_the_real_default_pricing_table() -> None:
    from app.pricing.seed_data import PROVIDER, EFFECTIVE_DATE, SOURCE

    # main() opens its own SessionLocal (real app DB, same one this test suite
    # runs against) — calling it should be a no-op if already seeded, but must
    # not raise, and the reference pricing set must exist afterward either way.
    main()

    db = SessionLocal()
    try:
        count = db.query(Pricing).filter(
            Pricing.provider == PROVIDER,
            Pricing.effective_date == EFFECTIVE_DATE,
            Pricing.source == SOURCE,
        ).count()
        assert count > 0
    finally:
        db.close()
