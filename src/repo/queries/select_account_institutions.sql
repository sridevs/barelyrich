SELECT DISTINCT a.institution,a.country_code,a.account_type FROM accounts a
LEFT JOIN institutions i ON i.key=a.institution WHERE i.key IS NULL;
