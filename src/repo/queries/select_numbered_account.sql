SELECT id,currency,is_liability FROM accounts
WHERE institution=? AND account_number=? AND currency=?;
