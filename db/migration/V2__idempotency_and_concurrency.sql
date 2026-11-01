-- What this file does:
--   Adds the extra database objects the API needs: the version column used for
--   PATCH (optimistic locking), and the table that stores cancel and refund keys.
--   It runs after 01_schema.sql, in alphabetical order.
--
-- Every statement uses IF NOT EXISTS, so it is safe to run more than once.

-- Optimistic locking for PATCH /version1/transactions/{id}
-- A version number that goes up on every change, so an old copy can be detected.
ALTER TABLE transactions  -- Change the existing transactions table.
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;  -- Add a whole-number column "version". Existing rows get 1. IF NOT EXISTS: skip if it is already there.

-- Idempotency storage for cancellation and refund requests
-- Creates a table that saves the answer to each cancel or refund key.
CREATE TABLE IF NOT EXISTS operation_idempotency (  -- Create only if it does not exist yet.
    operation VARCHAR(30) NOT NULL,  -- Which operation: "cancel" or "refund".
    idempotency_key UUID NOT NULL,  -- The client's key.
    request_hash CHAR(64) NOT NULL,  -- The 64-character SHA-256 fingerprint of the request.
    response_body JSONB NOT NULL,  -- The saved answer, stored as JSON.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When it was saved.
    PRIMARY KEY (operation, idempotency_key)  -- The pair must be unique: the same key can be used once per operation.
);
