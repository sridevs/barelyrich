CREATE UNIQUE INDEX IF NOT EXISTS idx_account_number
ON accounts(institution,account_number,currency) WHERE account_number IS NOT NULL;
