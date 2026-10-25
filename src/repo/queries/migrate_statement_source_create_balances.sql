CREATE TABLE account_balances_statement_migration (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
 as_of TEXT NOT NULL, balance TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('manual','csv','statement','tiger_api')),
 recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account_id,as_of)
);
