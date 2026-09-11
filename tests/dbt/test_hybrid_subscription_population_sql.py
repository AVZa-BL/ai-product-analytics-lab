"""Execute production eligibility SQL against invalid, delayed and DST fixtures."""

import re
from pathlib import Path

import duckdb
import pytest

MODEL_ROOT = Path("game_analytics/models/hybrid_subscription")
PREFIX = "int_hybrid_subscription__"


def build(db, name):
    path = MODEL_ROOT / "intermediate" / f"{PREFIX}{name}.sql"
    sql = re.sub(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", r"\1", path.read_text())
    db.execute(f"create or replace table {PREFIX}{name} as {sql}")


@pytest.fixture
def population_db():
    db = duckdb.connect()
    db.execute("set timezone='UTC'")
    db.execute("""
        create table stg_hybrid_subscription__players
        (player_id varchar, country_code varchar, platform varchar,
         acquisition_channel varchar, prior_payer_status varchar);
        insert into stg_hybrid_subscription__players values
        ('s','US','ios','organic','prior_payer'), ('c','US','ios','organic','prior_payer');
        create table stg_hybrid_subscription__subscription_events
        (player_id varchar, event_type varchar, occurred_at_utc timestamptz);
        insert into stg_hybrid_subscription__subscription_events values
        ('s','started','2026-03-02 00:00:00+00');
        create table int_hybrid_subscription__marketing_exposure_eligibility
        (player_id varchar, is_incrementality_eligible boolean, exposed_at_utc timestamptz);
        insert into int_hybrid_subscription__marketing_exposure_eligibility values
        ('s',true,'2026-03-01 00:00:00+00'), ('c',true,'2026-03-01 00:00:00+00');
        create table stg_hybrid_subscription__sessions
        (session_id varchar, player_id varchar, started_at_utc timestamptz,
         ingested_at_utc timestamptz, duration_seconds integer);
        insert into stg_hybrid_subscription__sessions values
        ('s1','s','2026-02-01 00:00:00+00','2026-02-01 00:05:00+00',60),
        ('s2','s','2026-03-30 00:00:00+00','2026-03-30 00:05:00+00',60),
        ('dst','s','2026-03-28 23:30:00+00','2026-03-28 23:35:00+00',60);
        create table fct_hybrid_subscription__sessions as
        select * from stg_hybrid_subscription__sessions;
        create table stg_hybrid_subscription__store_transactions
        (transaction_id varchar, player_id varchar, transaction_at_utc timestamptz,
         ingested_at_utc timestamptz, transaction_status varchar,
         recognized_net_revenue_usd double, discount_amount_usd double,
         is_subscription_revenue boolean, is_standalone_store_revenue boolean,
         is_reward_track_revenue boolean);
        insert into stg_hybrid_subscription__store_transactions values
        ('t1','s','2026-02-01 00:00:00+00','2026-02-01 00:02:00+00',
         'succeeded',1,0,false,true,false),
        ('t2','s','2026-03-30 00:00:00+00','2026-03-30 00:02:00+00',
         'succeeded',1,0,false,true,false);
        create table fct_hybrid_subscription__store_transactions as
        select * from stg_hybrid_subscription__store_transactions;
        create table stg_hybrid_subscription__live_event_participation
        (participation_id varchar, player_id varchar, participated_at_utc timestamptz,
         ingested_at_utc timestamptz);
        insert into stg_hybrid_subscription__live_event_participation values
        ('l1','s','2026-02-01 00:00:00+00','2026-02-01 00:06:00+00'),
        ('l2','s','2026-03-30 00:00:00+00','2026-03-30 00:06:00+00');
    """)
    yield db
    db.close()


def build_population(db):
    build(db, "source_watermarks")
    build(db, "governed_observation_boundary")
    build(db, "analysis_population")
    return db.sql(f"select * from {PREFIX}analysis_population order by player_id").df()


@pytest.mark.parametrize("source", ["sessions", "store_transactions", "live_event_participation"])
@pytest.mark.parametrize("failure", ["missing", "stale", "missing_ingestion", "late_ingestion"])
def test_each_source_must_cover_windows_and_pass_its_ingestion_allowance(
    population_db, source, failure
):
    db = population_db
    table = f"stg_hybrid_subscription__{source}"
    event = dict(
        sessions="started_at_utc",
        store_transactions="transaction_at_utc",
        live_event_participation="participated_at_utc",
    )[source]
    if failure == "missing":
        db.execute(f"delete from {table}")
    elif failure == "stale":
        db.execute(f"delete from {table} where {event} >= timestamptz '2026-03-01 00:00:00+00'")
    elif failure == "missing_ingestion":
        db.execute(f"update {table} set ingested_at_utc=null")
    else:
        # A backlogged old event raises the source-specific empirical allowance.
        # Fresh events have not yet advanced ingestion past post_end + that lag.
        db.execute(
            f"update {table} set ingested_at_utc={event}+interval '48 hours' "
            f"where {event}=timestamptz '2026-02-01 00:00:00+00'"
        )
    if source != "live_event_participation":
        db.execute(
            f"create or replace table fct_hybrid_subscription__{source} as select * from {table}"
        )
    result = build_population(db)
    assert not result.is_population_eligible.any(), (source, failure)
    assert result.exclusion_reason.notna().all()


@pytest.mark.parametrize(
    "column", ["player_id", "prior_payer_status", "platform", "acquisition_channel"]
)
@pytest.mark.parametrize("value", [None, "", "   ", "\t", "\n", "\t \n"])
def test_invalid_identity_or_matching_covariates_are_excluded(population_db, column, value):
    db = population_db
    db.execute(
        f"update stg_hybrid_subscription__players set {column}=? where player_id='s'", [value]
    )
    if column == "player_id":
        db.execute(
            "update int_hybrid_subscription__marketing_exposure_eligibility "
            "set player_id=? where player_id='s'",
            [value],
        )
    result = build_population(db)
    assert result.is_population_eligible.sum() == 1
    reason = "invalid_player_identity" if column == "player_id" else "invalid_matching_covariates"
    assert reason in result.exclusion_reason.tolist()
    build(db, "player_28d_behavior")
    assert db.sql(f"select distinct player_id from {PREFIX}player_28d_behavior").fetchall() == [
        ("c",)
    ]


@pytest.mark.parametrize("zone", ["America/Los_Angeles", "Europe/Berlin"])
def test_behavior_windows_are_exact_utc_durations_across_dst(population_db, zone):
    db = population_db
    db.execute(f"set timezone='{zone}'")
    build_population(db)
    build(db, "player_28d_behavior")
    post = db.sql(
        f"select epoch(period_end_at_utc)-epoch(index_at_utc), session_count "
        f"from {PREFIX}player_28d_behavior where player_id='s' and analysis_period='post'"
    ).fetchone()
    assert post == (28 * 86400, 1)


def test_delayed_ingestion_matures_only_after_source_watermark_advances(population_db):
    db = population_db
    db.execute(
        "update stg_hybrid_subscription__store_transactions "
        "set ingested_at_utc=transaction_at_utc+interval '48 hours' "
        "where transaction_id='t1'"
    )
    result = build_population(db)
    assert result.exclusion_reason.tolist() == ["ingestion_watermark_not_mature"] * 2
    db.execute(
        "update stg_hybrid_subscription__store_transactions "
        "set transaction_at_utc=timestamptz '2026-03-31 00:00:00+00', "
        "ingested_at_utc=timestamptz '2026-03-31 00:02:00+00' where transaction_id='t2'"
    )
    assert build_population(db).is_population_eligible.all()


def test_invalid_candidates_and_empty_matches_remain_in_governed_summary(population_db):
    db = population_db
    db.execute("update stg_hybrid_subscription__players set platform='' where player_id='s'")
    build_population(db)
    for name in ["player_28d_behavior", "matched_pairs", "match_population_summary"]:
        build(db, name)
    summary = db.sql(f"select * from {PREFIX}match_population_summary").df().iloc[0]
    assert summary.candidate_player_count == 2
    assert summary.excluded_player_count == summary.invalid_matching_covariates_count == 1
    assert summary.matched_pair_count == summary.eligible_subscriber_count == 0
    assert summary.eligible_control_count == summary.unmatched_control_count == 1
