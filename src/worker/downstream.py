import time
from typing import Any

from common.config import logger
from common.dynamo import get_or_create_fulfillment
from common.failure_injection import consume_failure_injection


class DownstreamServiceError(Exception):
    pass


class DownstreamTransientError(DownstreamServiceError):
    pass


class DownstreamPermanentError(DownstreamServiceError):
    pass


def call_downstream_fulfillment(
    order_id: str,
    fulfillment_key: str,
    verification_run_id: str | None = None,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Run a bounded deterministic simulation and return its idempotent result."""
    if consume_failure_injection(verification_run_id, scenario_id, "FULFILLMENT_FAIL") is not None:
        raise DownstreamTransientError("verification-injected fulfillment failure")
    delay = consume_failure_injection(verification_run_id, scenario_id, "FULFILLMENT_DELAY")
    if delay is not None and delay > 0:
        time.sleep(delay)
    result = {
        "status": "APPROVED",
        "authorization_code": f"AUTH-{order_id[:8].upper()}",
        "fulfillment_key": fulfillment_key,
    }
    saved_result = get_or_create_fulfillment(fulfillment_key, result)
    logger.info(
        "Simulated fulfillment completed",
        extra={"order_id": order_id, "fulfillment_key": fulfillment_key},
    )
    return saved_result
