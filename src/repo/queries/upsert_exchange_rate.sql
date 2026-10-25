INSERT INTO exchange_rates(base_currency,quote_currency,rate_date,rate,source)
VALUES(?,'INR',?,?,?)
ON CONFLICT(base_currency,quote_currency,rate_date,source) DO UPDATE SET
 rate=excluded.rate, fetched_at=CURRENT_TIMESTAMP;
