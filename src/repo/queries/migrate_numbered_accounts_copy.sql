INSERT INTO accounts_numbered
 (id,name,institution,country_code,account_type,currency,is_liability,created_at)
SELECT id,name,institution,country_code,account_type,currency,is_liability,created_at
FROM accounts;
