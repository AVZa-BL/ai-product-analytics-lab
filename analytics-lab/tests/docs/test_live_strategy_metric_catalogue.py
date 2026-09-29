from pathlib import Path


def test_every_live_strategy_metric_has_required_contract_fields() -> None:
    text = Path("docs/metrics/live_strategy.md").read_text()
    expected = [
        "New installs",
        "DAU",
        "D1 retention",
        "D7 retention",
        "Session frequency",
        "Median session duration",
        "Payer conversion",
        "ARPDAU",
        "Event participation",
        "Alliance adoption",
        "Progression velocity",
    ]

    for metric in expected:
        section = text.split(f"## {metric}", 1)[1].split("## ", 1)[0]
        for field in [
            "Source relation",
            "Grain",
            "Eligibility",
            "Exclusions",
            "Time rule",
            "Known limitations",
        ]:
            assert f"**{field}:**" in section
