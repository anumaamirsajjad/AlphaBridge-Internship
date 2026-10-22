-- Creates one pending test transaction from Anum to Maham (local dev database only).
INSERT INTO transactions (from_account_id, to_account_id, amount, currency, description, status)
SELECT a.account_id, b.account_id, 1.00, 'PKR', 'Pending test transaction', 'pending'
FROM accounts a, accounts b
WHERE a.account_holder = 'Anum' AND b.account_holder = 'Maham'
RETURNING transaction_id;
