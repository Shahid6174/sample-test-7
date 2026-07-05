from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid
import time
import base64

app = FastAPI()

# ---------------------------------------------------
# CORS
# ---------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],  # <-- FIX: without this, browsers can't
                                      # read the Retry-After header on 429s,
                                      # since it's not in the CORS-safelisted
                                      # response header set.
)

# ---------------------------------------------------
# Configuration
# ---------------------------------------------------
TOTAL_ORDERS = 48
RATE_LIMIT = 17          # requests
WINDOW = 10              # seconds

# ---------------------------------------------------
# Fixed Order Catalog (IDs 1..48)
# ---------------------------------------------------
orders_catalog = [
    {
        "id": i,
        "item": f"Item {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ---------------------------------------------------
# In-memory Stores
# ---------------------------------------------------
idempotency_store = {}
client_requests = {}

# ---------------------------------------------------
# Request Model
# ---------------------------------------------------
class OrderRequest(BaseModel):
    item: str = "Sample Item"


# ---------------------------------------------------
# Cursor Helpers
# ---------------------------------------------------
def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: str) -> int:
    return int(base64.urlsafe_b64decode(cursor.encode()).decode())


# ---------------------------------------------------
# Rate Limiter
# ---------------------------------------------------
def check_rate_limit(client_id: str):
    now = time.time()

    timestamps = client_requests.get(client_id, [])

    # Keep only timestamps within the last WINDOW seconds
    timestamps = [t for t in timestamps if now - t < WINDOW]

    client_requests[client_id] = timestamps

    if len(timestamps) >= RATE_LIMIT:
        retry_after = max(
            1,
            int(WINDOW - (now - timestamps[0])) + 1
        )

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)
    client_requests[client_id] = timestamps

    return None


# ---------------------------------------------------
# Root
# ---------------------------------------------------
@app.get("/")
def root():
    return {"status": "running"}


# ---------------------------------------------------
# POST /orders (Idempotent)
# ---------------------------------------------------
@app.post("/orders", status_code=201)
def create_order(
    order: OrderRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    client_id: str = Header(..., alias="X-Client-Id"),
):

    rate = check_rate_limit(client_id)

    if rate:
        return rate

    # Same idempotency key -> same response
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    created = {
        "id": str(uuid.uuid4()),
        "item": order.item
    }

    idempotency_store[idempotency_key] = created

    return JSONResponse(
        status_code=201,
        content=created
    )


# ---------------------------------------------------
# GET /orders (Cursor Pagination)
# ---------------------------------------------------
@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: str | None = None,
    client_id: str = Header(..., alias="X-Client-Id"),
):

    rate = check_rate_limit(client_id)

    if rate:
        return rate

    if limit < 1:
        limit = 1

    start = 0

    if cursor:
        try:
            start = decode_cursor(cursor)
        except Exception:
            start = 0

    end = min(start + limit, TOTAL_ORDERS)

    items = orders_catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor
    }