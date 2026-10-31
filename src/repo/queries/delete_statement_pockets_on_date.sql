DELETE FROM transactions WHERE as_of=? AND transaction_key='' AND account_id IN (
 SELECT id FROM accounts WHERE institution=? AND account_number=?
);
