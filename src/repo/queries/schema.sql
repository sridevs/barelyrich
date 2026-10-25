PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS institutions (
 key TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
 country_code TEXT NOT NULL DEFAULT '', account_type TEXT NOT NULL DEFAULT 'other'
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, institution TEXT NOT NULL,
 country_code TEXT NOT NULL, account_type TEXT NOT NULL, currency TEXT NOT NULL,
 is_liability INTEGER NOT NULL DEFAULT 0 CHECK(is_liability IN (0,1)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, account_number TEXT,
 product_type TEXT NOT NULL DEFAULT ''
);
-- Legacy transaction tables are inert compatibility storage; never delete saved records.
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
 transaction_date TEXT NOT NULL,
 transaction_type TEXT NOT NULL CHECK(transaction_type IN
 ('opening_balance','deposit','withdrawal','buy','sell','dividend','interest','fee',
 'transfer_in','transfer_out','liability_increase','liability_payment','adjustment')),
 amount TEXT NOT NULL, currency TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 external_id TEXT, transfer_group TEXT, source_file_hash TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account_id,external_id)
);
CREATE TABLE IF NOT EXISTS holdings (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
 symbol TEXT NOT NULL, asset_name TEXT NOT NULL, quantity TEXT NOT NULL,
 quote_currency TEXT NOT NULL, updated_on TEXT NOT NULL, UNIQUE(account_id,symbol)
);
CREATE TABLE IF NOT EXISTS exchange_rates (
 id INTEGER PRIMARY KEY, base_currency TEXT NOT NULL, quote_currency TEXT NOT NULL,
 rate_date TEXT NOT NULL, rate TEXT NOT NULL, source TEXT NOT NULL,
 fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(base_currency,quote_currency,rate_date,source)
);
CREATE TABLE IF NOT EXISTS asset_prices (
 id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, price_date TEXT NOT NULL,
 price TEXT NOT NULL, quote_currency TEXT NOT NULL, source TEXT NOT NULL,
 fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(symbol,price_date,source)
);
CREATE TABLE IF NOT EXISTS historical_fx_requests (
 currency TEXT NOT NULL, requested_date TEXT NOT NULL, rate_date TEXT NOT NULL,
 PRIMARY KEY(currency,requested_date)
);
CREATE TABLE IF NOT EXISTS wealth_snapshots (
 id INTEGER PRIMARY KEY, snapshot_date TEXT NOT NULL UNIQUE,
 total_assets_inr TEXT NOT NULL, total_liabilities_inr TEXT NOT NULL,
 net_worth_inr TEXT NOT NULL, fx_policy TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS backup_history (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 backup_path_label TEXT NOT NULL, status TEXT NOT NULL, checksum_sha256 TEXT,
 notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS account_balances (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
 as_of TEXT NOT NULL, balance TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('manual','csv','statement','tiger_api')),
 recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(account_id,as_of)
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_fx_date ON exchange_rates(rate_date);
CREATE INDEX IF NOT EXISTS idx_prices_symbol_date ON asset_prices(symbol,price_date);
-- Retained only for compatibility with databases from transaction-capture versions.
CREATE TABLE IF NOT EXISTS statement_transactions (
 id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id),
 source_file_hash TEXT NOT NULL, row_number INTEGER NOT NULL CHECK(row_number > 0),
 transaction_date TEXT NOT NULL, posting_date TEXT, description TEXT NOT NULL,
 amount TEXT NOT NULL, currency TEXT NOT NULL,
 direction TEXT NOT NULL CHECK(direction IN ('debit','credit')),
 running_balance TEXT, reference TEXT, page_number INTEGER NOT NULL CHECK(page_number > 0),
 quote TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(account_id,source_file_hash,row_number)
);
CREATE INDEX IF NOT EXISTS idx_statement_transactions_date
 ON statement_transactions(transaction_date);
