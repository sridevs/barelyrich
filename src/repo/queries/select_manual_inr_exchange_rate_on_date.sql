SELECT rate FROM exchange_rates WHERE base_currency=? AND quote_currency='INR'
AND source='manual' AND rate_date=?;
