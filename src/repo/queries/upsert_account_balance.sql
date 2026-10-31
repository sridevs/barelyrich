INSERT INTO transactions(
 account_id,as_of,balance,source,withdrawal,deposit,description,transaction_key,row_number
) VALUES(?,?,?,?,?,?,?,?,?)
ON CONFLICT(account_id,as_of,transaction_key) DO UPDATE SET
 balance=excluded.balance, source=excluded.source, withdrawal=excluded.withdrawal,
 deposit=excluded.deposit, description=excluded.description,
 row_number=MAX(transactions.row_number,excluded.row_number), recorded_at=CURRENT_TIMESTAMP;
