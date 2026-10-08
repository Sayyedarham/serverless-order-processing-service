import pytest

from verification.report import render_reliability_report


@pytest.mark.unit
def test_report_uses_only_provided_measurements() -> None:
    report = render_reliability_report(
        "verification-2026-10-08-001",
        [
            {"name": "Happy Path", "status": "PASSED", "metrics": {"requests": 2}},
            {"name": "Idempotency", "status": "PASSED", "metrics": {"duplicateOrders": 0}},
            {"name": "DLQ", "status": "FAILED", "metrics": {}},
        ],
    )

    assert "2 / 3 PASSED" in report
    assert "Requests               2" in report
    assert "Duplicate Orders       0" in report
    assert "P99" not in report
