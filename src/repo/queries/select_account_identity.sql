SELECT id, currency, is_liability FROM accounts
WHERE name=? AND institution=? AND account_number IS NULL;
