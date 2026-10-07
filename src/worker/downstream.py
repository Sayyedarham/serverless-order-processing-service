import time
from typing import Any

from common.config import logger
from common.dynamo import get_or_create_fulfillment


class DownstreamServiceError(Exception):
    pass


class DownstreamTransientError(DownstreamServiceError):
    pass


class DownstreamPermanentError(DownstreamServiceError):
    pass


def call_downstream_fulfillment(
    order_id: str, fulfillment_key: str, order_data: dict[str, Any]
) -> dict[str, Any]:
    """Run a bounded deterministic simulation and return its idempotent result."""
    customer_id = order_data.get("customerId") or order_data.get("payload", {}).get("customer_id")

    if customer_id in {"sim-fail-transient", "sim-timeout"}:
        logger.warning("Simulated fulfillment timeout", extra={"order_id": order_id})
        raise DownstreamTransientError(f"Simulated fulfillment timeout for order {order_id}")
    if customer_id in {"sim-fail-permanent", "sim-fail"}:
        logger.warning("Simulated permanent fulfillment failure", extra={"order_id": order_id})
        raise DownstreamPermanentError(
            f"Simulated fatal validation failure processing order {order_id}"
        )
    if customer_id == "sim-delay":
        time.sleep(0.1)

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
