"""The Banking API: the web addresses (routes) and their replies.

Run it with:
    uvicorn main:app --reload --host 127.0.0.1 --port 8081

Every route except the health check needs an X-API-Key header.
"""

from datetime import datetime
from uuid import UUID

import psycopg
from fastapi import FastAPI, Header, Query, Response
from fastapi.responses import JSONResponse

import banking
from banking import (
    AuthenticationError,
    BadRequestError,
    BankingError,
    PreconditionRequiredError,
    ServiceUnavailableError,
)
from database import connect, database_is_available
from schemas import (
    CancellationCreate,
    CancellationResponse,
    RefundCreate,
    RefundResponse,
    TransactionCreate,
    TransactionPage,
    TransactionResponse,
    TransactionStatus,
    TransactionUpdate,
)

app = FastAPI(title="Banking Transaction API", version="1.0.0")


# Checks the X-API-Key header. Returns the id of the client that owns the key.
def check_api_key(conn, api_key):
    if not api_key:
        raise AuthenticationError("An X-API-Key header is required.")
    client_id = banking.find_client_id(conn, api_key)
    if client_id is None:
        raise AuthenticationError("The API key is not valid.")
    return client_id


# Reads the Idempotency-Key header. It must be a UUID.
def read_idempotency_key(value):
    if not value:
        raise BadRequestError("The Idempotency-Key header is required.")
    try:
        return UUID(value)
    except ValueError:
        raise BadRequestError("Idempotency-Key must be a valid UUID.")


# Reads the If-Match header: the version the client last saw, for example "1".
def read_version(value):
    if value is None:
        raise PreconditionRequiredError('If-Match is required. Use the current version, e.g. "1".')
    try:
        version = int(value.strip().strip('"'))
    except ValueError:
        version = 0
    if version < 1:
        raise BadRequestError('If-Match must be a positive version number, e.g. "1".')
    return version


# Turns any BankingError into a reply with its status code.
def banking_error_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Turns any database error into a 503. The real error text is not shown to the caller.
def database_error_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Database operation failed."})


@app.get("/version1/health", tags=["Health"], summary="Check API and database health")
def health_check():
    if not database_is_available():
        raise ServiceUnavailableError("Database is unavailable")
    return {"status": "healthy", "database": "connected"}


@app.post(
    "/version1/transactions",
    status_code=201,
    response_model=TransactionResponse,
    tags=["Transactions"],
    summary="Transfer money from one of your accounts",
)
def create_transaction(
    payload: TransactionCreate,
    response: Response,
    x_api_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
):
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        key = read_idempotency_key(idempotency_key)
        transaction, created = banking.TransferService(conn, client_id).create(key, payload)
    # 201 for a new transfer, 200 when an earlier identical one is returned.
    response.status_code = 201 if created else 200
    return transaction


@app.get(
    "/version1/transactions",
    response_model=TransactionPage,
    tags=["Transactions"],
    summary="List your transactions",
)
def list_transactions(
    x_api_key: str | None = Header(default=None),
    status: TransactionStatus | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        items = banking.TransactionService(conn, client_id).list_all(
            status, from_date, to_date, limit, offset
        )
    return {"items": items, "limit": limit, "offset": offset}


@app.get(
    "/version1/transactions/{transaction_id}",
    response_model=TransactionResponse,
    tags=["Transactions"],
    summary="Get one of your transactions",
)
def read_transaction(transaction_id: UUID, x_api_key: str | None = Header(default=None)):
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        return banking.TransactionService(conn, client_id).get(transaction_id)


@app.patch(
    "/version1/transactions/{transaction_id}",
    response_model=TransactionResponse,
    tags=["Transactions"],
    summary="Change the description of a transaction you sent",
)
def update_transaction(
    transaction_id: UUID,
    payload: TransactionUpdate,
    x_api_key: str | None = Header(default=None),
    if_match: str | None = Header(default=None),
):
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        version = read_version(if_match)
        return banking.TransactionService(conn, client_id).update_description(
            transaction_id, payload.description, version
        )


@app.post(
    "/version1/transactions/{transaction_id}/cancellation",
    status_code=201,
    response_model=CancellationResponse,
    tags=["Transactions"],
    summary="Cancel a pending transaction you sent",
)
def cancel_transaction(
    transaction_id: UUID,
    response: Response,
    x_api_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
    payload: CancellationCreate | None = None,
):
    # The body is optional. Without one, the default reason is used.
    if payload is None:
        payload = CancellationCreate()
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        key = read_idempotency_key(idempotency_key)
        answer, created = banking.CancellationService(conn, client_id).cancel(transaction_id, key, payload)
    response.status_code = 201 if created else 200
    return answer


@app.post(
    "/version1/transactions/{transaction_id}/refunds",
    status_code=201,
    response_model=RefundResponse,
    tags=["Transactions"],
    summary="Refund all or part of a transaction you sent",
)
def refund_transaction(
    transaction_id: UUID,
    payload: RefundCreate,
    response: Response,
    x_api_key: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
):
    with connect() as conn:
        client_id = check_api_key(conn, x_api_key)
        key = read_idempotency_key(idempotency_key)
        answer, created = banking.RefundService(conn, client_id).refund(transaction_id, key, payload)
    response.status_code = 201 if created else 200
    return answer


app.add_exception_handler(BankingError, banking_error_handler)
app.add_exception_handler(psycopg.Error, database_error_handler)
