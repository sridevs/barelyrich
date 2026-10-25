INSERT INTO institutions(key,name,normalized_name,country_code,account_type)
VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING;
