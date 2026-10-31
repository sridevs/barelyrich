WITH dated_transactions AS (
 SELECT * FROM transactions WHERE as_of<=?
), ranked_transactions AS (
 SELECT *, ROW_NUMBER() OVER (
  PARTITION BY account_id,as_of
  ORDER BY (transaction_key='') DESC,row_number DESC,recorded_at DESC,id DESC
 ) AS position FROM dated_transactions
), latest_pockets AS (
 SELECT a.id,a.institution,a.account_number,MAX(b.as_of) AS as_of
 FROM accounts a JOIN dated_transactions b ON b.account_id=a.id GROUP BY a.id
), latest_statements AS (
 SELECT a.institution,a.account_number,MAX(b.as_of) AS as_of
 FROM accounts a JOIN dated_transactions b ON b.account_id=a.id
 WHERE a.account_number IS NOT NULL AND b.transaction_key=''
 GROUP BY a.institution,a.account_number
)
SELECT a.*, i.name AS institution_name, i.country_code AS institution_country,
i.account_type AS institution_type, b.balance, b.as_of, b.source, b.recorded_at FROM accounts a
JOIN institutions i ON i.key=a.institution
JOIN latest_pockets p ON p.id=a.id
LEFT JOIN latest_statements s
 ON s.institution=a.institution AND s.account_number=a.account_number
JOIN ranked_transactions b ON a.id=b.account_id AND b.as_of=p.as_of
AND (s.as_of IS NULL OR p.as_of>=s.as_of)
AND b.position=1
ORDER BY a.institution,a.name,a.currency;
