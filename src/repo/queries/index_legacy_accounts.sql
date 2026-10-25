CREATE UNIQUE INDEX IF NOT EXISTS idx_account_alias
ON accounts(institution,name) WHERE account_number IS NULL;
