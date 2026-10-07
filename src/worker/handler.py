import json
import time
from typing import Any

from aws_lambda_powertools.metrics import MetricUnit

from common.config import MAX_RECEIVE_COUNT, logger, metrics, tracer
from common.dynamo import get_order, update_order_status
from common.models import OrderStatus
from worker.downstream import (
    DownstreamPermanentError,
    DownstreamTransientError,
    call_downstream_fulfillment,
)


@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics(capture_cold_start_metric=True)
@tracer.capture_lambda_handler
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    records = event.get("Records", [])
    batch_item_failures: list[dict[str, str]] = []

    logger.info("Processing SQS batch", extra={"batch_size": len(records)})

    for record in records:
        message_id = record.get("messageId", "")
        start_time = time.perf_counter()

        try:
            body = json.loads(record.get("body", "{}"))
            order_id = body.get("orderId")
            idempotency_key = body.get("idempotencyKey")
            payload = body.get("payload", {})

            if not order_id:
                logger.error(
                    "SQS record missing orderId, skipping without retry",
                    extra={"message_id": message_id},
                )
                continue

            logger.append_keys(
                order_id=order_id, idempotency_key=idempotency_key, message_id=message_id
            )

            current_order = get_order(order_id)
            if not current_order:
                logger.warning(
                    "Order not found in DynamoDB during worker execution",
                    extra={"order_id": order_id},
                )
                batch_item_failures.append({"itemIdentifier": message_id})
                continue

            current_status = current_order.get("status")
            if current_status == OrderStatus.COMPLETED.value:
                logger.info(
                    "Order is already COMPLETED, skipping downstream call",
                    extra={"order_id": order_id},
                )
                continue

            update_order_status(
                order_id=order_id,
                status=OrderStatus.PROCESSING,
                processed_by=getattr(context, "function_name", "local-worker"),
            )

            fulfillment_key = f"{order_id}:FULFILLMENT"
            call_downstream_fulfillment(
                order_id=order_id,
                fulfillment_key=fulfillment_key,
                order_data=current_order,
            )

            update_order_status(order_id=order_id, status=OrderStatus.COMPLETED)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            metrics.add_metric(name="OrdersCompleted", unit=MetricUnit.Count, value=1)
            metrics.add_metric(
                name="ProcessingLatency", unit=MetricUnit.Milliseconds, value=elapsed_ms
            )
            logger.info(
                "Order processed successfully",
                extra={"order_id": order_id, "latency_ms": elapsed_ms},
            )

        except DownstreamTransientError as transient_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            metrics.add_metric(name="OrdersFailed", unit=MetricUnit.Count, value=1)
            receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
            if receive_count >= MAX_RECEIVE_COUNT and "order_id" in locals() and order_id:
                update_order_status(
                    order_id=order_id, status=OrderStatus.DLQ, error_message=str(transient_err)
                )
                logger.error("Retry limit reached; order marked DLQ", extra={"receive_count": receive_count})
            logger.warning(
                "Transient downstream failure, scheduling SQS retry via partial batch failure",
                extra={"error": str(transient_err), "latency_ms": elapsed_ms},
            )
            batch_item_failures.append({"itemIdentifier": message_id})

        except DownstreamPermanentError as permanent_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            metrics.add_metric(name="OrdersFailed", unit=MetricUnit.Count, value=1)
            logger.error(
                "Permanent downstream failure, marking order as FAILED without retry",
                extra={"error": str(permanent_err), "latency_ms": elapsed_ms},
            )
            if "order_id" in locals() and order_id:
                update_order_status(
                    order_id=order_id, status=OrderStatus.FAILED, error_message=str(permanent_err)
                )

        except Exception as unexpected_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            metrics.add_metric(name="OrdersFailed", unit=MetricUnit.Count, value=1)
            logger.exception(
                "Unexpected error processing SQS record", extra={"error": str(unexpected_err)}
            )
            batch_item_failures.append({"itemIdentifier": message_id})

    logger.info(
        "Finished batch processing",
        extra={"total": len(records), "failures": len(batch_item_failures)},
    )
    return {"batchItemFailures": batch_item_failures}
