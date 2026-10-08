import json
from typing import Any

import pytest

from common.sqs import get_sqs_client
from verification import handler, runner
from verification.storage import (
    create_run,
    get_run,
    get_scenario_results,
    put_scenario_result,
    set_run_status,
)


@pytest.mark.unit
def test_verification_api_persists_queues_and_reads_results(
    setup_dynamodb: Any, setup_sqs: Any, lambda_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    verification_url = get_sqs_client().create_queue(QueueName="verification")["QueueUrl"]
    monkeypatch.setattr(handler, "VERIFICATION_QUEUE_URL", verification_url)
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "rawPath": "/verification/runs",
        "headers": {"X-Service-Key": "test-secret-key"},
        "body": json.dumps({"scenarios": ["happy-path"]}),
    }
    response = handler.lambda_handler(event, lambda_context)
    assert response["statusCode"] == 202
    run_id = json.loads(response["body"])["runId"]
    assert get_run(run_id)["status"] == "QUEUED"  # type: ignore[index]
    put_scenario_result(run_id, "happy-path", {"name": "happy-path", "status": "PASSED"})
    results_event = {
        "requestContext": {"http": {"method": "GET"}},
        "rawPath": f"/verification/runs/{run_id}/results",
        "pathParameters": {"runId": run_id},
        "headers": {"X-Service-Key": "test-secret-key"},
    }
    read = handler.lambda_handler(results_event, lambda_context)
    assert read["statusCode"] == 200
    assert json.loads(read["body"])["results"][0]["status"] == "PASSED"


@pytest.mark.unit
def test_verification_api_rejects_unauthorized_and_unbounded_requests(
    setup_dynamodb: Any, lambda_context: Any
) -> None:
    assert handler.lambda_handler({"headers": {}}, lambda_context)["statusCode"] == 401
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "rawPath": "/verification/runs",
        "headers": {"X-Service-Key": "test-secret-key"},
        "body": json.dumps({"scenarios": ["not-allowed"]}),
    }
    assert handler.lambda_handler(event, lambda_context)["statusCode"] == 422


@pytest.mark.unit
def test_storage_lifecycle(setup_dynamodb: Any) -> None:
    run = create_run("run-storage", ["happy-path"])
    assert run["status"] == "QUEUED"
    assert set_run_status("run-storage", "RUNNING")["status"] == "RUNNING"
    put_scenario_result("run-storage", "happy-path", {"name": "happy-path", "status": "PASSED"})
    assert get_scenario_results("run-storage")[0]["scenarioId"] == "happy-path"
    assert set_run_status("run-storage", "FAILED", "boom")["error"] == "boom"


@pytest.mark.unit
def test_runner_fixed_scenarios_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_wait_for_terminal", lambda _: (True, {"status": "COMPLETED"}))
    monkeypatch.setattr(runner, "_submit", lambda *_args: (202, {"orderId": "one"}))
    assert runner._run_live("run", "happy-path")["status"] == "PASSED"
    monkeypatch.setattr(runner, "_submit", lambda *_args: (200, {"orderId": "one"}))
    assert runner._run_live("run", "duplicate-request")["status"] == "FAILED"
    monkeypatch.setattr(runner, "_submit", lambda *_args: (202, {"orderId": "one"}))
    assert runner._run_live("run", "concurrent-duplicate")["status"] == "PASSED"
    assert (
        runner._run_live("run", "small-load")["metrics"]["requests"] == runner.SMALL_LOAD_REQUESTS
    )
    assert runner._run_live("run", "dlq")["status"] == "SKIPPED"


@pytest.mark.unit
def test_runner_marks_failed_run_on_error(
    setup_dynamodb: Any, lambda_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_run("run-fail", ["happy-path"])
    monkeypatch.setattr(runner, "API_BASE_URL", "https://example.test")
    monkeypatch.setattr(runner, "SERVICE_KEY", "key")
    monkeypatch.setattr(
        runner, "_run_live", lambda *_: (_ for _ in ()).throw(RuntimeError("broken"))
    )
    runner.lambda_handler(
        {"Records": [{"body": json.dumps({"runId": "run-fail"})}]}, lambda_context
    )
    assert get_run("run-fail")["status"] == "FAILED"  # type: ignore[index]
