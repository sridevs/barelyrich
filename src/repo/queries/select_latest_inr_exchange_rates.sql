SELECT base_currency,rate,rate_date FROM exchange_rates r
WHERE quote_currency='INR' AND source IN ('manual','frankfurter') AND rate_date=(
SELECT MAX(r2.rate_date) FROM exchange_rates r2
WHERE r2.base_currency=r.base_currency AND r2.quote_currency='INR'
AND r2.source IN ('manual','frankfurter') AND r2.rate_date<=?)
ORDER BY CASE source WHEN 'frankfurter' THEN 1 ELSE 0 END;
