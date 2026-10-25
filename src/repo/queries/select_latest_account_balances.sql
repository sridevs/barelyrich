WITH latest_pockets AS (
 SELECT a.id,a.institution,a.account_number,MAX(b.as_of) AS as_of
 FROM accounts a JOIN account_balances b ON b.account_id=a.id
 WHERE b.as_of<=? GROUP BY a.id
), latest_statements AS (
 SELECT institution,account_number,MAX(as_of) AS as_of FROM latest_pockets
 WHERE account_number IS NOT NULL GROUP BY institution,account_number
)
SELECT a.*, i.name AS institution_name, i.country_code AS institution_country,
i.account_type AS institution_type, b.balance, b.as_of, b.source, b.recorded_at FROM accounts a
JOIN institutions i ON i.key=a.institution
JOIN latest_pockets p ON p.id=a.id
LEFT JOIN latest_statements s
 ON s.institution=a.institution AND s.account_number=a.account_number
JOIN account_balances b ON a.id=b.account_id AND b.as_of=COALESCE(s.as_of,p.as_of)
ORDER BY a.institution,a.name,a.currency;
