SELECT a.institution, a.name AS account, a.account_number, a.product_type, a.currency, b.as_of, b.balance,
b.source, b.recorded_at FROM account_balances b JOIN accounts a ON a.id=b.account_id
WHERE b.as_of<=? ORDER BY b.as_of DESC,a.institution,a.name;
