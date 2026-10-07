import random
from typing import Any

from common.config import DOWNSTREAM_FAILURE_RATE, logger


class DownstreamServiceError(Exception):
    pass


class DownstreamTransientError(DownstreamServiceError):
    pass


class DownstreamPermanentError(DownstreamServiceError):
    pass


def call_downstream_fulfillment(order_id: str, order_data: dict[str, Any]) -> dict[str, Any]:
    customer_id = order_data.get("customerId") or order_data.get("payload", {}).get("customer_id")
    if customer_id == "sim-fail-transient":
        logger.warning(
            "Simulated deterministic transient failure triggered", extra={"order_id": order_id}
        )
        raise DownstreamTransientError(f"Simulated transient timeout processing order {order_id}")

    if customer_id == "sim-fail-permanent":
        logger.warning(
            "Simulated deterministic permanent failure triggered", extra={"order_id": order_id}
        )
        raise DownstreamPermanentError(
            f"Simulated fatal validation failure processing order {order_id}"
        )

    if DOWNSTREAM_FAILURE_RATE > 0.0:
        roll = random.random()
        if roll < DOWNSTREAM_FAILURE_RATE:
            logger.warning(
                "Simulated probabilistic transient failure",
                extra={"order_id": order_id, "roll": roll, "rate": DOWNSTREAM_FAILURE_RATE},
            )
            raise DownstreamTransientError(
                f"Downstream service unavailable (rate={DOWNSTREAM_FAILURE_RATE}, roll={roll:.3f})"
            )

    logger.info("Downstream fulfillment succeeded", extra={"order_id": order_id})
    return {
        "status": "APPROVED",
        "authorization_code": f"AUTH-{order_id[:8].upper()}",
    }
