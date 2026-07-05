from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import time
import base64

app = FastAPI()

# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allows grader/browser
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Configuration
# ----------------------------

TOTAL_ORDERS = 48
RATE_LIMIT = 17
WINDOW = 10  # seconds

# ----------------------------
# Fixed Catalog
# ----------------------------

orders_catalog = [
    {
        "id": i,
        "item": f"Item {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ----------------------------
# Idempotency Store
# ----------------------------

idempotency_store = {}

# ----------------------------
# Rate Limit Store
# ----------------------------

client_requests = {}

# ----------------------------
# Models
# ----------------------------

class OrderRequest(BaseModel):
    item: str = "Sample Item"


# ======================================================
# Rate Limiter
# ======================================================

def check_rate_limit(client_id: str):

    now = time.time()

    if client_id not in client_requests:
        client_requests[client_id] = []

    # remove expired timestamps
    client_requests[client_id] = [
        t for t in client_requests[client_id]
        if now - t < WINDOW
    ]

    if len(client_requests[client_id]) >= RATE_LIMIT:

        retry_after = int(WINDOW - (now - client_requests[client_id][0])) + 1

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)}
        )

    client_requests[client_id].append(now)


# ======================================================
# POST /orders
# ======================================================

@app.post("/orders", status_code=201)
def create_order(
    order: OrderRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(client_id)

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    created = {
        "id": str(uuid.uuid4()),
        "item": order.item
    }

    idempotency_store[idempotency_key] = created

    return created


# ======================================================
# Cursor Helpers
# ======================================================

def encode_cursor(index: int):

    return base64.urlsafe_b64encode(
        str(index).encode()
    ).decode()


def decode_cursor(cursor: str):

    return int(
        base64.urlsafe_b64decode(cursor.encode()).decode()
    )


# ======================================================
# GET /orders
# ======================================================

@app.get("/orders")
def list_orders(
    limit: int = 10,
    cursor: str | None = None,
    client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(client_id)

    start = 0

    if cursor:
        start = decode_cursor(cursor)

    end = min(start + limit, TOTAL_ORDERS)

    items = orders_catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor
    }


# ======================================================
# Health
# ======================================================

@app.get("/")
def root():
    return {"status": "running"}