"""Synthetic demo data for the e-commerce target API.

No real users, credentials, or production data — this is a local hackathon fixture.
"""

from __future__ import annotations

from typing import Literal

Mode = Literal["vulnerable", "secure"]

USERS: dict[str, dict] = {
    "alice-token": {
        "id": "user-101",
        "name": "Alice",
        "role": "customer",
        "email": "alice@example.com",
        "phone": "+1-555-0101",
        "address": "18 Lake View Road",
        "date_of_birth": "1994-03-12",
    },
    "bob-token": {
        "id": "user-102",
        "name": "Bob",
        "role": "customer",
        "email": "bob@example.com",
        "phone": "+1-555-0102",
        "address": "42 Park Street",
        "date_of_birth": "1988-11-02",
    },
    "admin-token": {
        "id": "admin-001",
        "name": "Priya",
        "role": "admin",
        "email": "priya@example.com",
        "phone": "+1-555-0110",
        "address": "1 HQ Plaza",
    },
}

ORDERS: dict[str, dict] = {
    "order-1001": {
        "id": "order-1001",
        "user_id": "user-101",
        "items": ["Wireless Keyboard", "USB-C Hub"],
        "total": 79.98,
        "shipping_address": "18 Lake View Road",
        "status": "delivered",
    },
    "order-1002": {
        "id": "order-1002",
        "user_id": "user-102",
        "items": ["Noise-Cancelling Headphones"],
        "total": 149.99,
        "shipping_address": "42 Park Street",
        "status": "shipped",
    },
}

PRODUCTS: list[dict] = [
    {"id": "prod-001", "name": "Wireless Keyboard", "price": 39.99, "in_stock": True},
    {"id": "prod-002", "name": "USB-C Hub", "price": 39.99, "in_stock": True},
    {"id": "prod-003", "name": "Noise-Cancelling Headphones", "price": 149.99, "in_stock": True},
]
