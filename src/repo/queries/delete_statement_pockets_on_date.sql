DELETE FROM account_balances WHERE as_of=? AND account_id IN (
 SELECT id FROM accounts WHERE institution=? AND account_number=?
);
