INSERT INTO accounts(name,institution,country_code,account_type,currency,is_liability,account_number,product_type)
VALUES(?,?,?,?,?,?,?,?) RETURNING id;
