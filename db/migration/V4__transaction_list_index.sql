-- flyway:executeInTransaction=false
-- Speeds up GET /version1/transactions, which sorts by created_at DESC, transaction_id.
-- CONCURRENTLY builds the index without blocking reads or writes on the live table.
-- It cannot run inside a transaction, so Flyway runs this file outside one (the line above).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_transactions_created_at_id
    ON transactions (created_at DESC, transaction_id);
