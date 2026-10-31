INSERT INTO precious_metal_valuations(transaction_id,price_id,quantity) VALUES(?,?,?)
ON CONFLICT(transaction_id) DO UPDATE SET
 price_id=excluded.price_id, quantity=excluded.quantity;
