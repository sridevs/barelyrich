INSERT INTO accounts_numbered
 (id,name,institution,country_code,account_type,currency,is_liability)
SELECT id,name,institution,country_code,account_type,currency,is_liability FROM accounts;
