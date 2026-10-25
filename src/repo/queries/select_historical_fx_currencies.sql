SELECT h.currency FROM historical_fx_requests h
JOIN exchange_rates r ON r.base_currency=h.currency AND r.quote_currency='INR'
AND r.rate_date=h.rate_date AND r.source='frankfurter'
WHERE h.requested_date=?;
