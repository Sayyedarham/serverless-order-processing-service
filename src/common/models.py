from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OrderStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrderItem(BaseModel):
    item_id: str = Field(
        ..., min_length=1, max_length=64, description="Unique identifier for the item"
    )
    name: str = Field(..., min_length=1, max_length=128, description="Product name")
    quantity: int = Field(..., gt=0, le=1000, description="Quantity of items")
    price: float = Field(..., ge=0.0, description="Unit price of the item")


class OrderCreateRequest(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64, description="Customer identifier")
    items: list[OrderItem] = Field(
        ..., min_length=1, max_length=50, description="List of items in order"
    )
    total_amount: float | None = Field(
        default=None, ge=0.0, description="Total order amount (computed if omitted)"
    )

    @field_validator("items")
    @classmethod
    def validate_non_empty_items(cls, v: list[OrderItem]) -> list[OrderItem]:
        if not v:
            raise ValueError("Order must contain at least one item")
        return v

    def calculate_total(self) -> float:
        calculated = sum(item.quantity * item.price for item in self.items)
        return round(calculated, 2)


class OrderRecord(BaseModel):
    orderId: str
    idempotencyKey: str
    customerId: str
    status: OrderStatus
    items: list[dict[str, Any]]
    totalAmount: float
    createdAt: str
    updatedAt: str
    expiresAt: int
    errorMessage: str | None = None
    processedBy: str | None = None
