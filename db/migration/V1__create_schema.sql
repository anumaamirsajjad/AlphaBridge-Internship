-- Line-by-line notes: each line below is either a SQL comment (starts with --)
-- or a SQL statement. Comments are ignored by the database.
--
-- What this file does:
--   Creates the core database tables when the database is first started.
--   It runs automatically (see docker-compose.yml), only on an empty database.
--   Tables: accounts, transactions, refunds, cancellations, idempotency_keys.

-- ACCOUNTS: one row per bank account. Balance can never go below zero.
CREATE TABLE accounts (  -- Create a new table called "accounts".
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Unique ID. UUID type. PRIMARY KEY: must be unique and not empty. Default: a random UUID is generated automatically.
    account_holder VARCHAR(100) NOT NULL,  -- Account owner's name, up to 100 characters. NOT NULL: must be filled in.
    currency CHAR(3) NOT NULL,  -- Currency code, exactly 3 characters (CHAR pads shorter values).
    balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,  -- Money amount: up to 15 digits, 2 after the point. Exact (no rounding errors). Default 0.00.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- When the account was created, with time zone. Default: now.

    CONSTRAINT accounts_balance_nonnegative  -- A named rule. The name helps when an error message appears.
        CHECK (balance >= 0),  -- The balance must be zero or more. The database refuses any change that breaks this.

    CONSTRAINT accounts_currency_format  -- Named rule for the currency format.
        CHECK (currency ~ '^[A-Z]{3}$')  -- ~ means "matches the regular expression": exactly three capital letters.
);  -- End of the CREATE TABLE statement.


-- TRANSACTIONS: one row per money movement.
CREATE TABLE transactions (  -- Create the transactions table.
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Unique ID, generated automatically.
    from_account_id UUID NOT NULL REFERENCES accounts(account_id),  -- Sender. REFERENCES: must be an existing account (a foreign key).
    to_account_id UUID NOT NULL REFERENCES accounts(account_id),  -- Receiver. Also must be an existing account.
    amount DECIMAL(15,2) NOT NULL,  -- How much was moved.
    currency CHAR(3) NOT NULL,  -- Currency code.
    description VARCHAR(255) NOT NULL,  -- Text up to 255 characters.
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- Status text. New rows default to 'pending'.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- When it was created.
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- When it last changed. Starts as the creation time.

    CONSTRAINT transactions_amount_positive  -- Named rule.
        CHECK (amount > 0),  -- The amount must be greater than zero.

    CONSTRAINT transactions_different_accounts  -- Named rule.
        CHECK (from_account_id <> to_account_id),  -- <> means "not equal": sender and receiver must differ.

    CONSTRAINT transactions_status_valid  -- Named rule.
        CHECK (status IN (  -- The status must be one of the values in the list below.
            'pending', 'completed', 'failed',
            'cancelled', 'refunded'
        )),

    CONSTRAINT transactions_currency_format  -- Named rule for the currency format.
        CHECK (currency ~ '^[A-Z]{3}$')  -- Three capital letters.
);


-- REFUNDS: a record each time money is returned for a transaction.
CREATE TABLE refunds (  -- Create the refunds table.
    refund_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Unique ID.
    transaction_id UUID NOT NULL  -- The transaction being refunded.
        REFERENCES transactions(transaction_id),  -- Must be an existing transaction (foreign key).
    amount DECIMAL(15,2) NOT NULL,  -- Amount refunded.
    reason VARCHAR(255) NOT NULL,  -- Why it was refunded.
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- Status. Defaults to pending.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- When created.

    CONSTRAINT refunds_amount_positive  -- Named rule.
        CHECK (amount > 0),  -- Must be greater than zero.

    CONSTRAINT refunds_status_valid  -- Named rule.
        CHECK (status IN ('pending', 'processed', 'rejected'))  -- Allowed statuses.
);


-- CANCELLATIONS: a record when a pending transaction is cancelled.
CREATE TABLE cancellations (  -- Create the cancellations table.
    cancellation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- Unique ID.
    transaction_id UUID NOT NULL UNIQUE  -- The cancelled transaction. UNIQUE: a transaction can be cancelled only once.
        REFERENCES transactions(transaction_id),  -- Must be an existing transaction.
    reason VARCHAR(255) NOT NULL,  -- Why it was cancelled.
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- Status. Defaults to pending.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- When created.

    CONSTRAINT cancellations_status_valid  -- Named rule.
        CHECK (status IN ('pending', 'completed', 'rejected'))  -- Allowed statuses.
);


-- IDEMPOTENCY KEYS: remembers which transfer each key created.
CREATE TABLE idempotency_keys (  -- Create the idempotency_keys table.
    idempotency_key UUID PRIMARY KEY,  -- The key sent by the client. PRIMARY KEY: each key can only be used once.
    transaction_id UUID NOT NULL UNIQUE  -- The transaction the key created. UNIQUE: one transaction per key.
        REFERENCES transactions(transaction_id),  -- Must be an existing transaction.
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP  -- When the key was saved.
);


-- Helpful indexes for looking up transactions
-- An index is a lookup table that makes searches faster.
CREATE INDEX idx_transactions_from_account  -- Name of the index.
    ON transactions(from_account_id);  -- Speeds up searches by sender.

CREATE INDEX idx_transactions_to_account  -- Name of the index.
    ON transactions(to_account_id);  -- Speeds up searches by receiver.

CREATE INDEX idx_refunds_transaction  -- Name of the index.
    ON refunds(transaction_id);  -- Speeds up finding refunds for a transaction.
