INSERT INTO account_balances(account_id,as_of,balance,source) VALUES(?,?,?,?)
ON CONFLICT(account_id,as_of) DO UPDATE SET
 balance=excluded.balance, source=excluded.source, recorded_at=CURRENT_TIMESTAMP;
