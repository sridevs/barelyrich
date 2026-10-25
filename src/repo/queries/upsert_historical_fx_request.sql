INSERT INTO historical_fx_requests(currency,requested_date,rate_date) VALUES(?,?,?)
ON CONFLICT(currency,requested_date) DO UPDATE SET rate_date=excluded.rate_date;
