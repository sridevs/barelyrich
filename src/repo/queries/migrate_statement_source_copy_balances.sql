INSERT INTO account_balances_statement_migration
SELECT id,account_id,as_of,balance,source,recorded_at FROM account_balances;
