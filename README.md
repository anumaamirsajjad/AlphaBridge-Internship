# Banking API

A small banking API built with FastAPI and PostgreSQL. It runs in Docker.

Every call except the health check needs an **API key** in the `X-API-Key`
header. A client can only send money from its own accounts, and can only see or
change the transactions it is part of.

## Project layout

```
banking-db/
├── docker-compose.yml      Starts the database and the API together
├── init/                   SQL run once, when the database is first created
│   ├── 01_schema.sql           accounts, transactions, refunds, cancellations
│   ├── 02_idempotency_and_concurrency.sql
│   └── 03_api_clients.sql      API clients and which accounts they may use
├── api/
│   ├── main.py             Routes, API-key check, headers, error replies
│   ├── banking.py          Banking rules, access rules, and the SQL
│   ├── schemas.py          Request and reply shapes
│   ├── database.py         Database connection
│   ├── create_api_key.py   Tool: creates an API key for a client
│   ├── tests/              Automated tests (run against banking_test)
│   ├── Dockerfile          Builds the API image
│   ├── requirements.txt    Packages the API needs (pinned versions)
│   └── requirements-dev.txt  Extra packages for testing
└── eval.txt                Writeup: principles, practices, setup history
```

## Run it

```powershell
cd C:\Users\MTS\banking-db
docker compose up -d --build
```

Swagger UI: http://127.0.0.1:8081/docs (each route has an `X-API-Key` field to fill in).

## Create an API key

Run from the `api` folder, with `DATABASE_URL` pointing at the database:

```powershell
python create_api_key.py "Ali's mobile app" "Ali Ahmed" "Maham"
```

The key is printed **once**. Only its hash is stored, so copy it immediately.
Every account name must match exactly one account, or nothing is saved.

## Run the tests

```powershell
cd api
.\.venv\Scripts\python.exe -m pytest
```

The tests use a separate `banking_test` database, so `banking_db` is never changed.

## Stop it

```powershell
docker compose down      # keeps the data
```

Do not add `-v`: that deletes the database volume.
