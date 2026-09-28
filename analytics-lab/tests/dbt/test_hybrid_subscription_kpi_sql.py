"""Execute production KPI SQL on hand-checked canonical-fact fixtures.

These tests catch failed/refunded/reward transaction classification, repeated-player
overcounting, cancellation-as-churn, incomplete cohorts and zero-denominator rates.
They complement, but do not replace, owner-run dbt source-to-mart validation.
"""

import re
from pathlib import Path

import duckdb
import pytest

ROOT = Path("game_analytics")
MART = "mart_hybrid_subscription__"


def render(path):
    assert path.exists(), f"Missing governed KPI contract: {path.name}"
    return re.sub(r"\{\{\s*ref\('([^']+)'\)\s*\}\}", r"\1", path.read_text())


@pytest.fixture
def facts():
    db = duckdb.connect()
    db.execute("set timezone='UTC'")
    db.execute("""
        create table dim_dates as select cast(d as date) date_day
        from generate_series(date '2026-01-01', date '2026-04-30', interval '1 day') t(d);
        create table dim_hybrid_subscription__players
        (player_id varchar, prior_payer_status varchar, is_subscriber boolean);
        insert into dim_hybrid_subscription__players values
        ('a','prior_payer',true),('b','prior_payer',true),('c','prior_nonpayer',false),
        ('d','prior_nonpayer',true),('e','prior_nonpayer',true);
        create table fct_hybrid_subscription__sessions
        (session_id varchar, player_id varchar, started_at_utc timestamptz, duration_seconds int);
        insert into fct_hybrid_subscription__sessions values
        ('s1','a','2026-01-01 01:00:00+00',60),('s2','a','2026-01-01 02:00:00+00',120),
        ('s3','c','2026-01-20 00:00:00+00',90),('s4','a','2026-03-01 00:00:00+00',40);
        create table stg_hybrid_subscription__live_event_participation
        (participation_id varchar, player_id varchar, participated_at_utc timestamptz);
        insert into stg_hybrid_subscription__live_event_participation values
        ('l1','a','2026-01-05 00:00:00+00'),('l2','a','2026-01-06 00:00:00+00'),
        ('l3','b','2026-01-06 00:00:00+00');
        create table fct_hybrid_subscription__store_transactions
        (transaction_id varchar, player_id varchar, prior_payer_status varchar,
        transaction_at_utc timestamptz, transaction_status varchar,
        is_standalone_store_revenue boolean, is_subscription_revenue boolean,
        is_reward_track_revenue boolean, recognized_net_revenue_usd decimal(18,2),
        discount_amount_usd decimal(18,2));
        insert into fct_hybrid_subscription__store_transactions values
        ('t1','a','prior_payer','2026-01-01 03:00:00+00','succeeded',true,false,false,8,2),
        ('t2','a','prior_payer','2026-01-02 00:00:00+00','refunded',true,false,false,0,0),
        ('t3','a','prior_payer','2026-01-03 00:00:00+00','failed',true,false,false,0,3),
        ('t4','a','prior_payer','2026-01-04 00:00:00+00','succeeded',false,true,false,10,0),
        ('t5','c','prior_nonpayer','2026-01-05 00:00:00+00','succeeded',false,false,true,100,0);
        create table fct_hybrid_subscription__subscription_entitlements
        (subscription_id varchar, player_id varchar, entitlement_start_at_utc timestamptz,
        entitlement_end_at_utc timestamptz, canceled_at_utc timestamptz,
        terminal_event_at_utc timestamptz);
        insert into fct_hybrid_subscription__subscription_entitlements values
        ('a1','a','2026-01-01 00:00:00+00','2026-03-15 00:00:00+00','2026-01-20 00:00:00+00',null),
        ('b1','b','2026-01-01 00:00:00+00','2026-01-31 00:00:00+00',null,'2026-01-31 00:00:00+00'),
        ('d1','d','2026-02-01 12:00:00+00','2026-04-01 00:00:00+00',null,null),
        ('e1','e','2026-02-01 00:00:00+00','2026-04-01 00:00:00+00',null,null);
        create table stg_hybrid_subscription__subscription_events
        (player_id varchar, event_type varchar, occurred_at_utc timestamptz);
        insert into stg_hybrid_subscription__subscription_events values
        ('a','started','2026-01-01 00:00:00+00'),('a','canceled','2026-01-20 00:00:00+00'),
        ('b','started','2026-01-01 00:00:00+00'),('b','expired','2026-01-31 00:00:00+00'),
        ('d','started','2026-02-01 12:00:00+00'),('e','started','2026-02-01 00:00:00+00');
        create table fct_hybrid_subscription__subscriber_daily as
        select e.player_id, e.subscription_id, d.date_day metric_date
        from fct_hybrid_subscription__subscription_entitlements e join dim_dates d
        on d.date_day >= cast(e.entitlement_start_at_utc as date)
        and d.date_day < cast(e.entitlement_end_at_utc as date);
        create table fct_hybrid_subscription__marketing_exposures
        (exposure_id varchar, player_id varchar, exposed_at_utc timestamptz,
        is_incrementality_eligible boolean);
        insert into fct_hybrid_subscription__marketing_exposures values
        ('x1','a','2025-12-31 12:00:00+00',true),('x2','a','2025-12-31 13:00:00+00',true),
        ('x3','b','2025-12-31 12:00:00+00',true),('x4','c','2025-12-31 12:00:00+00',true),
        ('x5','d','2026-02-01 00:00:00+00',true),('x6','e','2026-02-01 12:00:00+00',false);
        create table fct_hybrid_subscription__currency_grants
        (player_id varchar, occurred_at_utc timestamptz, entry_type varchar, is_reconciled boolean);
        insert into fct_hybrid_subscription__currency_grants values
        ('a','2026-01-01 03:00:00+00','subscription_grant',true),
        ('b','2026-01-01 03:00:00+00','subscription_grant',false),
        ('c','2026-01-19 03:00:00+00','reward_grant',true);
        create table stg_hybrid_subscription__sessions as
        select * from fct_hybrid_subscription__sessions;
        insert into stg_hybrid_subscription__sessions values
        ('raw_duplicate','a','2026-01-01 01:00:00+00',60);
        alter table fct_hybrid_subscription__store_transactions add column product_type varchar;
        update fct_hybrid_subscription__store_transactions set product_type = case
            when is_subscription_revenue then 'subscription'
            when is_reward_track_revenue then 'reward_track' else 'currency_pack' end;
        create table int_hybrid_subscription__governed_observation_boundary
        (observation_start_at_utc timestamptz, as_of_at_utc timestamptz,
        are_source_watermarks_valid boolean);
        insert into int_hybrid_subscription__governed_observation_boundary values
        ('2025-12-31 12:00:00+00','2026-03-01 00:00:00+00',true);
        create table int_hybrid_subscription__source_watermarks
        (source_name varchar, observation_start_at_utc timestamptz,
        ingestion_mature_through_at_utc timestamptz, is_source_valid boolean);
        insert into int_hybrid_subscription__source_watermarks values
        ('sessions','2025-12-31 12:00:00+00','2026-03-01 00:00:00+00',true),
        ('store_transactions','2025-12-31 12:00:00+00','2026-03-01 00:00:00+00',true),
        ('live_event_participation','2025-12-31 12:00:00+00','2026-03-01 00:00:00+00',true);
    """)
    yield db
    db.close()


def build(db, name):
    db.execute(
        f"create table {MART}{name} as "
        + render(ROOT / "models/hybrid_subscription/marts" / f"{MART}{name}.sql")
    )


def row(db, name, condition):
    result = db.execute(f"select * from {MART}{name} where {condition}")
    return dict(zip([c[0] for c in result.description], result.fetchone(), strict=True))


def test_monthly_distinct_populations_cash_categories_and_churn(facts):
    build(facts, "monthly_kpis")
    january = row(facts, "monthly_kpis", "metric_month = date '2026-01-01'")
    expected = dict(
        mau=2,
        month_start_active_subscriber_count=2,
        month_end_active_subscriber_count=1,
        expired_or_revoked_entitlement_count=1,
        subscriber_churn_rate=0.5,
        standalone_store_net_revenue_usd=8,
        subscription_net_revenue_usd=10,
        total_net_revenue_usd=18,
        arpmau=9,
        eligible_standalone_transaction_count=2,
        discounted_standalone_transaction_count=1,
        discount_utilization_rate=0.5,
        liveops_participant_count=1,
        liveops_participation_rate=0.5,
    )
    for key, value in expected.items():
        assert january[key] == value, key
    february = row(facts, "monthly_kpis", "metric_month = date '2026-02-01'")
    assert february["mau"] == 0
    assert all(
        february[c] is None
        for c in ["arpmau", "liveops_participation_rate", "discount_utilization_rate"]
    )


def test_daily_uses_canonical_sessions_and_distinct_active_players(facts):
    # An entitlement-level duplicate must not inflate player-level active counts.
    facts.execute("""
        insert into fct_hybrid_subscription__subscriber_daily
        select * from fct_hybrid_subscription__subscriber_daily where player_id='a'
    """)
    build(facts, "daily_kpis")
    daily = row(
        facts, "daily_kpis", "metric_date=date '2026-01-01' and prior_payer_status='prior_payer'"
    )
    assert daily["session_count"] == 2
    assert daily["session_duration_seconds"] == 180
    assert daily["active_subscriber_count"] == 2
    assert daily["subscription_grant_reconciliation_rate"] == 0.5
    assert (
        facts.execute(f"select sum(total_net_revenue_usd) from {MART}daily_kpis").fetchone()[0]
        == 18
    )
    assert (
        facts.execute(f"""
        select count(*) from (select metric_date,prior_payer_status
        from {MART}daily_kpis group by all having count(*)>1)
    """).fetchone()[0]
        == 0
    )


def test_cohorts_first_eligible_exposure_exact_maturity_and_d30_expiry(facts):
    build(facts, "subscription_cohorts")
    conversion = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2025-12-31'",
    )
    assert conversion["eligible_exposed_player_count"] == 3
    assert conversion["converted_within_28d_player_count"] == 2
    assert conversion["subscription_conversion_rate"] == pytest.approx(2 / 3)
    retention = row(
        facts,
        "subscription_cohorts",
        "cohort_type='subscription_start' and cohort_date=date '2026-01-01'",
    )
    assert retention["mature_subscription_starter_count"] == 2
    assert retention["retained_at_d30_player_count"] == 1
    assert retention["d30_subscriber_retention_rate"] == 0.5
    immature = row(
        facts,
        "subscription_cohorts",
        "cohort_type='subscription_start' and cohort_date=date '2026-02-01'",
    )
    assert immature["d30_subscriber_retention_rate"] is None
    assert immature["mature_subscription_starter_count"] == 0
    exact = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2026-02-01'",
    )
    assert exact["is_conversion_mature"] is True
    assert exact["subscription_conversion_rate"] == 1


def test_singular_contracts_reject_corrupted_components_and_nulls(facts):
    for name in ["daily_kpis", "monthly_kpis", "subscription_cohorts"]:
        build(facts, name)
    checks = {
        name: render(ROOT / "tests/hybrid_subscription" / f"assert_hybrid_{name}.sql")
        for name in ["kpis_reconcile", "zero_denominators_are_null", "cohort_maturity"]
    }
    for sql in checks.values():
        assert facts.execute(sql).fetchall() == []
    # Each published component and ratio must be independently checked, not only
    # checked against other (potentially coherently corrupted) published columns.
    for name in ["daily_kpis", "monthly_kpis", "subscription_cohorts"]:
        columns = facts.execute(f"describe {MART}{name}").fetchall()
        for column, dtype, *_ in columns:
            if dtype not in ("BIGINT", "HUGEINT", "DOUBLE", "DECIMAL(38,2)"):
                continue
            for replacement in [f"coalesce({column},0)+1", "null"]:
                facts.execute("begin")
                facts.execute(f"update {MART}{name} set {column} = {replacement}")
                assert facts.execute(checks["kpis_reconcile"]).fetchall(), (name, column)
                facts.execute("rollback")
        for mutation in [
            f"insert into {MART}{name} select * from {MART}{name} limit 1",
            f"delete from {MART}{name}",
        ]:
            facts.execute("begin")
            facts.execute(mutation)
            assert facts.execute(checks["kpis_reconcile"]).fetchall(), (name, mutation)
            facts.execute("rollback")
    facts.execute(f"update {MART}monthly_kpis set arpmau=0 where mau=0")
    assert facts.execute(checks["zero_denominators_are_null"]).fetchall()
    facts.execute(f"""
        update {MART}subscription_cohorts set d30_subscriber_retention_rate=1
        where not is_d30_mature
    """)
    assert facts.execute(checks["cohort_maturity"]).fetchall()


def test_partial_month_and_month_opening_instant(facts):
    build(facts, "monthly_kpis")
    february = row(facts, "monthly_kpis", "metric_month=date '2026-02-01'")
    # a remains entitled after cancellation; e starts at midnight; d starts at noon.
    assert february["month_start_active_subscriber_count"] == 2
    march = row(facts, "monthly_kpis", "metric_month=date '2026-03-01'")
    assert march["is_month_complete"] is False
    assert march["month_end_active_subscriber_count"] is None


@pytest.mark.parametrize("zone", ["America/Los_Angeles", "Europe/Berlin"])
@pytest.mark.parametrize("name", ["daily_kpis", "monthly_kpis", "subscription_cohorts"])
def test_kpi_dates_and_maturity_do_not_depend_on_connection_timezone(facts, zone, name):
    sql = render(ROOT / "models/hybrid_subscription/marts" / f"{MART}{name}.sql")

    # JSON serializes timestamptz instants consistently; compare epochs for them.
    def values():
        result = facts.sql(sql)
        columns = result.columns
        types = result.types
        projection = ",".join(
            f"epoch({column}) as {column}" if str(dtype) == "TIMESTAMP WITH TIME ZONE" else column
            for column, dtype in zip(columns, types, strict=True)
        )
        return facts.sql(f"select {projection} from ({sql}) order by 1").fetchall()

    expected = values()
    facts.execute(f"set timezone='{zone}'")
    assert values() == expected


@pytest.mark.parametrize(
    "column,mutation",
    [
        ("is_month_complete", "not is_month_complete"),
        ("as_of_at_utc", "as_of_at_utc + interval '1 hour'"),
        ("is_month_complete", "null"),
        ("as_of_at_utc", "null"),
    ],
)
def test_monthly_reconciliation_rejects_corrupted_maturity(facts, column, mutation):
    for name in ["daily_kpis", "monthly_kpis", "subscription_cohorts"]:
        build(facts, name)
    facts.execute(f"update {MART}monthly_kpis set {column}={mutation}")
    check = render(ROOT / "tests/hybrid_subscription/assert_hybrid_kpis_reconcile.sql")
    assert facts.sql(check).fetchall()


def test_d30_uses_elapsed_utc_time_across_dst(facts):
    facts.execute("""
        insert into fct_hybrid_subscription__sessions values
        ('d30-boundary','c','2026-03-31 00:00:00+00',1);
        insert into fct_hybrid_subscription__subscription_entitlements values
        ('c1','c','2026-03-01 00:00:00+00','2026-03-30 23:30:00+00',null,null);
        update int_hybrid_subscription__governed_observation_boundary
        set as_of_at_utc='2026-03-31 00:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set ingestion_mature_through_at_utc='2026-03-31 00:00:00+00';
        set timezone='America/Los_Angeles';
    """)
    build(facts, "subscription_cohorts")
    cohort = row(
        facts,
        "subscription_cohorts",
        "cohort_type='subscription_start' and cohort_date=date '2026-03-01'",
    )
    assert cohort["is_d30_mature"] is True
    assert cohort["mature_subscription_starter_count"] == 1
    assert cohort["retained_at_d30_player_count"] == 0


def test_subscriber_daily_fact_uses_utc_dates_independent_of_connection(facts):
    sql = render(
        ROOT / "models/hybrid_subscription/marts/fct_hybrid_subscription__subscriber_daily.sql"
    )
    expected = facts.sql(f"select player_date_id from ({sql}) order by 1").fetchall()
    for zone in ["America/Los_Angeles", "Europe/Berlin"]:
        facts.execute(f"set timezone='{zone}'")
        assert facts.sql(f"select player_date_id from ({sql}) order by 1").fetchall() == expected


def test_cohort_maturity_waits_for_latest_member_on_same_date(facts):
    facts.execute("""
        insert into fct_hybrid_subscription__sessions values
        ('watermark','c','2026-03-03 00:00:00+00',1);
        insert into fct_hybrid_subscription__marketing_exposures values
        ('x7','c','2026-02-01 12:00:00+00',true);
        update int_hybrid_subscription__governed_observation_boundary
        set as_of_at_utc='2026-03-03 00:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set ingestion_mature_through_at_utc='2026-03-03 00:00:00+00';
    """)
    build(facts, "subscription_cohorts")
    mixed = row(
        facts,
        "subscription_cohorts",
        "cohort_type='subscription_start' and cohort_date=date '2026-02-01'",
    )
    assert mixed["subscription_starter_count"] == 2
    assert mixed["mature_subscription_starter_count"] == 1
    assert mixed["retained_at_d30_player_count"] == 1
    assert mixed["is_d30_mature"] is False
    assert mixed["d30_subscriber_retention_rate"] is None
    facts.execute(f"drop table {MART}subscription_cohorts")
    facts.execute("""
        update int_hybrid_subscription__governed_observation_boundary
        set as_of_at_utc='2026-03-03 12:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set ingestion_mature_through_at_utc='2026-03-03 12:00:00+00';
    """)
    build(facts, "subscription_cohorts")
    mature = row(
        facts,
        "subscription_cohorts",
        "cohort_type='subscription_start' and cohort_date=date '2026-02-01'",
    )
    assert mature["mature_subscription_starter_count"] == 2
    assert mature["is_d30_mature"] is True
    assert mature["d30_subscriber_retention_rate"] == 1


def test_conversion_half_open_end_and_exact_as_of_boundary(facts):
    facts.execute("""
        update fct_hybrid_subscription__marketing_exposures
        set exposed_at_utc='2026-01-04 12:00:00+00' where player_id='d';
    """)
    build(facts, "subscription_cohorts")
    cohort = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2026-01-04'",
    )
    assert cohort["eligible_exposed_player_count"] == 1
    assert cohort["converted_within_28d_player_count"] == 0
    assert cohort["subscription_conversion_rate"] == 0


def test_no_observations_publishes_no_speculative_rows(facts):
    for source in [
        "fct_hybrid_subscription__sessions",
        "fct_hybrid_subscription__store_transactions",
        "stg_hybrid_subscription__live_event_participation",
    ]:
        facts.execute(f"delete from {source}")
    facts.execute("""
        update int_hybrid_subscription__governed_observation_boundary
        set are_source_watermarks_valid=false, observation_start_at_utc=null,
            as_of_at_utc=null;
        update int_hybrid_subscription__source_watermarks
        set is_source_valid=false, observation_start_at_utc=null,
            ingestion_mature_through_at_utc=null;
    """)
    for name in ["daily_kpis", "monthly_kpis", "subscription_cohorts"]:
        build(facts, name)
        assert facts.execute(f"select count(*) from {MART}{name}").fetchone()[0] == 0
    for name in ["kpis_reconcile", "zero_denominators_are_null", "cohort_maturity"]:
        assert (
            facts.execute(
                render(ROOT / "tests/hybrid_subscription" / f"assert_hybrid_{name}.sql")
            ).fetchall()
            == []
        )


def test_conversion_day_cohort_waits_for_last_exposure_timestamp(facts):
    facts.execute("""
        update fct_hybrid_subscription__marketing_exposures
        set exposed_at_utc='2026-02-01 12:00:00+00' where exposure_id='x4';
    """)
    build(facts, "subscription_cohorts")
    mixed = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2026-02-01'",
    )
    assert mixed["eligible_exposed_player_count"] == 2
    assert mixed["converted_within_28d_player_count"] == 1
    assert mixed["is_conversion_mature"] is False
    assert mixed["subscription_conversion_rate"] is None
    facts.execute(f"drop table {MART}subscription_cohorts")
    facts.execute("""
        update int_hybrid_subscription__governed_observation_boundary
        set as_of_at_utc='2026-03-01 12:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set ingestion_mature_through_at_utc='2026-03-01 12:00:00+00';
    """)
    build(facts, "subscription_cohorts")
    mature = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2026-02-01'",
    )
    assert mature["is_conversion_mature"] is True
    assert mature["subscription_conversion_rate"] == 0.5


def test_churn_zero_opening_balance_and_revocation(facts):
    facts.execute("""
        update fct_hybrid_subscription__subscription_entitlements
        set entitlement_start_at_utc=entitlement_start_at_utc+interval '12 hours'
        where player_id in ('a','b');
        update stg_hybrid_subscription__subscription_events
        set event_type='revoked' where event_type='expired';
    """)
    build(facts, "monthly_kpis")
    january = row(facts, "monthly_kpis", "metric_month=date '2026-01-01'")
    assert january["month_start_active_subscriber_count"] == 0
    assert january["expired_or_revoked_entitlement_count"] == 1
    assert january["subscriber_churn_rate"] is None


def test_lagging_source_boundary_withholds_cohort_and_month_maturity(facts):
    facts.execute("""
        insert into fct_hybrid_subscription__store_transactions values
        ('after-as-of','a','prior_payer','2026-01-20 12:00:00+00',
         'succeeded',true,false,false,50,0,'currency_pack');
        update int_hybrid_subscription__governed_observation_boundary
        set as_of_at_utc='2026-01-15 00:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set ingestion_mature_through_at_utc='2026-01-15 00:00:00+00'
        where source_name='store_transactions';
    """)
    build(facts, "monthly_kpis")
    build(facts, "subscription_cohorts")

    january = row(facts, "monthly_kpis", "metric_month=date '2026-01-01'")
    assert january["as_of_at_utc"] == facts.execute(
        "select timestamptz '2026-01-15 00:00:00+00'"
    ).fetchone()[0]
    assert january["is_month_complete"] is False
    assert january["month_end_active_subscriber_count"] is None
    assert january["mau"] == 1
    assert january["standalone_store_net_revenue_usd"] == 8

    conversion = row(
        facts,
        "subscription_cohorts",
        "cohort_type='eligible_exposure' and cohort_date=date '2025-12-31'",
    )
    assert conversion["as_of_at_utc"] == january["as_of_at_utc"]
    assert conversion["is_conversion_mature"] is False
    assert conversion["subscription_conversion_rate"] is None


def test_partial_first_month_and_precoverage_cohorts_are_suppressed(facts):
    facts.execute("""
        update int_hybrid_subscription__governed_observation_boundary
        set observation_start_at_utc='2026-01-02 00:00:00+00';
        update int_hybrid_subscription__source_watermarks
        set observation_start_at_utc='2026-01-02 00:00:00+00'
        where source_name='live_event_participation';
    """)
    build(facts, "monthly_kpis")
    build(facts, "subscription_cohorts")

    assert facts.execute(f"""
        select count(*) from {MART}monthly_kpis
        where metric_month=date '2026-01-01'
    """).fetchone()[0] == 0
    assert facts.execute(f"""
        select count(*) from {MART}subscription_cohorts
        where cohort_date < date '2026-01-02'
    """).fetchone()[0] == 0
