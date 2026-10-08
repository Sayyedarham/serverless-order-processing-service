from collections.abc import Iterable
from typing import Any


def render_reliability_report(run_id: str, scenarios: Iterable[dict[str, Any]]) -> str:
    """Render only measurements present in structured scenario results."""
    results = list(scenarios)
    passed = sum(result.get("status") == "PASSED" for result in results)
    lines = ["ORDER PIPELINE RELIABILITY REPORT", "", f"Run: {run_id}", "", "Tests", "-----"]
    lines.extend(
        f"{'✓' if result.get('status') == 'PASSED' else '✗'} {result.get('name', 'Unnamed scenario')}"
        for result in results
    )
    lines.extend(["", f"{passed} / {len(results)} PASSED"])
    metrics = _measurements(results)
    if metrics:
        lines.extend(["", "Measurements", "------------"])
        lines.extend(f"{label:<22} {value}" for label, value in metrics.items())
    return "\n".join(lines)


def _measurements(results: list[dict[str, Any]]) -> dict[str, Any]:
    aliases = {
        "duplicateOrders": "Duplicate Orders",
        "lostMessages": "Lost Messages",
        "invalidTransitions": "Invalid Transitions",
        "requests": "Requests",
        "p50": "P50",
        "p95": "P95",
        "p99": "P99",
    }
    values: dict[str, Any] = {}
    for result in results:
        for key, value in result.get("metrics", {}).items():
            if key in aliases and isinstance(value, (int, float)):
                values[aliases[key]] = values.get(aliases[key], 0) + value
    return values
