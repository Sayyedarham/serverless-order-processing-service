"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from common.models import OrderCreateRequest, OrderItem, OrderRecord, OrderStatus


@pytest.mark.unit
def test_order_item_valid() -> None:
    item = OrderItem(item_id="item-101", name="Wireless Mouse", quantity=2, price=29.99)
    assert item.item_id == "item-101"
    assert item.quantity == 2
    assert item.price == 29.99


@pytest.mark.unit
def test_order_item_invalid_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderItem(item_id="item-101", name="Mouse", quantity=0, price=29.99)


@pytest.mark.unit
def test_order_item_negative_price() -> None:
    with pytest.raises(ValidationError):
        OrderItem(item_id="item-101", name="Mouse", quantity=1, price=-5.0)


@pytest.mark.unit
def test_order_create_request_total_calculation() -> None:
    req = OrderCreateRequest(
        customer_id="cust-123",
        items=[
            OrderItem(item_id="item-1", name="Book", quantity=2, price=15.50),
            OrderItem(item_id="item-2", name="Pen", quantity=3, price=2.00),
        ],
    )
    assert req.calculate_total() == 37.0


@pytest.mark.unit
def test_order_create_request_empty_items() -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest(customer_id="cust-123", items=[])


@pytest.mark.unit
def test_order_record_serialization() -> None:
    record = OrderRecord(
        orderId="test-order-id",
        idempotencyKey="idem-key-1",
        customerId="cust-123",
        status=OrderStatus.RECEIVED,
        items=[{"item_id": "i-1", "name": "Item 1", "quantity": 1, "price": 10.0}],
        totalAmount=10.0,
        createdAt="2026-10-06T00:00:00Z",
        updatedAt="2026-10-06T00:00:00Z",
        expiresAt=1800000000,
    )
    dumped = record.model_dump()
    assert dumped["orderId"] == "test-order-id"
    assert dumped["status"] == "RECEIVED"
