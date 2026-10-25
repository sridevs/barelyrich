CREATE TABLE accounts_numbered (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, institution TEXT NOT NULL,
 country_code TEXT NOT NULL, account_type TEXT NOT NULL, currency TEXT NOT NULL,
 is_liability INTEGER NOT NULL DEFAULT 0 CHECK(is_liability IN (0,1)),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, account_number TEXT
);
