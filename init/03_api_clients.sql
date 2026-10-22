-- What this file does:
--   Adds authorization tables. Every API call must carry an API key, and each
--   key belongs to a client. A client may only use the accounts linked to it.
--   Runs after 01 and 02, in alphabetical order. Safe to run more than once.

-- API clients: one row per app or person that may call the API.
-- Only a SHA-256 hash of the key is stored. The real key is never in the database.
CREATE TABLE IF NOT EXISTS api_clients (
    client_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Unique ID of the client.
    name VARCHAR(100) NOT NULL,                             -- Readable name, e.g. "Ali's mobile app".
    key_hash CHAR(64) NOT NULL UNIQUE,                      -- SHA-256 hash of the API key (64 hex characters).
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()           -- When the client was created.
);

-- Which accounts each client may use. A client can only send money from these accounts.
CREATE TABLE IF NOT EXISTS client_accounts (
    client_id UUID NOT NULL REFERENCES api_clients(client_id),  -- The client.
    account_id UUID NOT NULL REFERENCES accounts(account_id),   -- An account the client may use.
    PRIMARY KEY (client_id, account_id)                          -- Each link appears only once.
);
