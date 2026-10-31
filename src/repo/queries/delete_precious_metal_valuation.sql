DELETE FROM precious_metal_valuations WHERE transaction_id=(
 SELECT id FROM transactions WHERE account_id=? AND as_of=? AND transaction_key=?
);
