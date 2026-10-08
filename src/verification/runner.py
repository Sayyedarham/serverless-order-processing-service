"""Bounded Lambda worker for the fixed, live verification scenario allowlist."""

import json
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from common.config import API_BASE_URL, SERVICE_KEY, TTL_DAYS, logger
from common.dynamo import InvalidStateTransitionError, put_order_if_not_exists, update_order_status
from common.failure_injection import create_failure_injection
from common.models import OrderRecord, OrderStatus
from verification.report import render_reliability_report
from verification.storage import get_run, put_scenario_result, set_run_status

# The order queue batches for up to five seconds and Lambda cold starts can
# add latency. Keep this bounded while leaving room for two live scenarios in
# the runner's 60-second hard timeout.
POLL_SECONDS = 25
SMALL_LOAD_REQUESTS = 10  # deliberately below the documented hard maximum of 100


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if SERVICE_KEY:
        request_headers["X-Service-Key"] = SERVICE_KEY
    request = urllib.request.Request(
        f"{API_BASE_URL.rstrip('/')}{path}", data=payload, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310: configured BYOK endpoint
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def _order_payload() -> dict[str, Any]:
    return {
        "customer_id": "verification",
        "items": [{"item_id": "probe", "name": "Probe", "quantity": 1, "price": 1.0}],
    }


def _submit(run_id: str, scenario_id: str, key: str | None = None) -> tuple[int, dict[str, Any]]:
    key = key or f"verify-{run_id}-{scenario_id}-{uuid.uuid4()}"
    return _request(
        "POST",
        "/orders",
        _order_payload(),
        {
            "Idempotency-Key": key,
            "X-Verification-Run-Id": run_id,
            "X-Verification-Scenario-Id": scenario_id,
        },
    )


def _wait_for_terminal(order_id: str) -> tuple[bool, dict[str, Any]]:
    deadline = time.monotonic() + POLL_SECONDS
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        code, last = _request("GET", f"/orders/{order_id}")
        order = last.get("order", last)
        if code == 200 and order.get("status") in {"COMPLETED", "FAILED", "DLQ"}:
            return order["status"] == "COMPLETED", last
        time.sleep(1)
    return False, last


def _result(
    name: str, status: str, evidence: dict[str, Any], metrics: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "completedAt": int(time.time()),
        "evidence": evidence,
        "metrics": metrics or {},
    }


def _run_live(run_id: str, scenario_id: str) -> dict[str, Any]:
    if scenario_id == "happy-path":
        code, accepted = _submit(run_id, scenario_id)
        success, order = (
            _wait_for_terminal(accepted.get("orderId", "")) if code == 202 else (False, {})
        )
        return _result(
            scenario_id, "PASSED" if success else "FAILED", {"submitStatus": code, "order": order}
        )
    if scenario_id == "duplicate-request":
        key = f"verify-{run_id}-{scenario_id}"
        first_code, first = _submit(run_id, scenario_id, key)
        second_code, second = _submit(run_id, scenario_id, key)
        success, order = (
            _wait_for_terminal(first.get("orderId", "")) if first_code == 202 else (False, {})
        )
        passed = success and second_code == 200 and first.get("orderId") == second.get("orderId")
        return _result(
            scenario_id,
            "PASSED" if passed else "FAILED",
            {"first": first_code, "second": second_code, "order": order},
            {"duplicateOrders": 0 if passed else 1},
        )
    if scenario_id == "concurrent-duplicate":
        key = f"verify-{run_id}-{scenario_id}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: _submit(run_id, scenario_id, key), range(2)))
        ids = {reply[1].get("orderId") for reply in replies}
        return _result(
            scenario_id,
            "PASSED" if len(ids) == 1 and ids != {None} else "FAILED",
            {"statusCodes": [reply[0] for reply in replies], "orderIds": list(ids)},
        )
    if scenario_id == "small-load":
        started = time.perf_counter()
        replies = [_submit(run_id, scenario_id) for _ in range(SMALL_LOAD_REQUESTS)]
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        accepted_count = sum(status_code == 202 for status_code, _ in replies)
        return _result(
            scenario_id,
            "PASSED" if accepted_count == SMALL_LOAD_REQUESTS else "FAILED",
            {"accepted": accepted_count, "durationMs": elapsed},
            {"requests": SMALL_LOAD_REQUESTS},
        )
    if scenario_id in {"worker-failure", "downstream-failure"}:
        action = "WORKER" if scenario_id == "worker-failure" else "FULFILLMENT_FAIL"
        create_failure_injection(run_id, scenario_id, action, max_requests=1)
        code, accepted = _submit(run_id, scenario_id)
        return _result(
            scenario_id,
            "SKIPPED",
            {
                "submitStatus": code,
                "orderId": accepted.get("orderId"),
                "reason": "retry/DLQ timing exceeds this runner's bounded wait",
            },
        )
    if scenario_id == "state-transition":
        now = int(time.time())
        order_id = f"verification-state-{run_id}-{uuid.uuid4()}"
        put_order_if_not_exists(
            OrderRecord(
                orderId=order_id,
                idempotencyKey=f"verification-{uuid.uuid4()}",
                customerId="verification",
                status=OrderStatus.RECEIVED,
                items=[],
                totalAmount=0,
                createdAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                updatedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                expiresAt=now + TTL_DAYS * 86400,
                correlationId=run_id,
            )
        )
        update_order_status(order_id, OrderStatus.PROCESSING, processed_by="verification-runner")
        update_order_status(order_id, OrderStatus.COMPLETED)
        try:
            update_order_status(order_id, OrderStatus.PROCESSING)
        except InvalidStateTransitionError:
            return _result(
                scenario_id,
                "PASSED",
                {"orderId": order_id, "invalidTransition": "COMPLETED -> PROCESSING rejected"},
                {"invalidTransitions": 0},
            )
        return _result(
            scenario_id,
            "FAILED",
            {"orderId": order_id, "reason": "invalid transition was accepted"},
            {"invalidTransitions": 1},
        )
    return _result(
        scenario_id,
        "SKIPPED",
        {
            "reason": "scenario needs an isolated DLQ/redrive probe not yet available in this deployment"
        },
    )


@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    for record in event.get("Records", []):
        run_id = json.loads(record["body"])["runId"]
        try:
            run = get_run(run_id)
            if not run:
                logger.error("Verification run does not exist", extra={"run_id": run_id})
                continue
            if not API_BASE_URL or not SERVICE_KEY:
                raise RuntimeError("verification runner requires API_BASE_URL and API_SHARED_KEY")
            set_run_status(run_id, "RUNNING")
            results = []
            for scenario_id in run["scenarios"]:
                result = _run_live(run_id, scenario_id)
                put_scenario_result(run_id, scenario_id, result)
                results.append(result)
            set_run_status(run_id, "COMPLETED")
            logger.info(
                render_reliability_report(run_id, results), extra={"verification_run_id": run_id}
            )
        except Exception as err:
            logger.exception("Verification run failed", extra={"verification_run_id": run_id})
            set_run_status(run_id, "FAILED", str(err))
    return {"batchItemFailures": []}
