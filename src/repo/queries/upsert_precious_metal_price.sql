INSERT INTO precious_metal_prices(
 metal,purity,currency,unit,price,observed_at,source
) VALUES(?,?,?,?,?,?,?)
ON CONFLICT(metal,purity,currency,unit,observed_at,source) DO UPDATE SET
 price=excluded.price,fetched_at=CURRENT_TIMESTAMP
RETURNING id;
