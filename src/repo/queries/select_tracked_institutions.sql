SELECT DISTINCT i.* FROM institutions i JOIN accounts a ON a.institution=i.key
ORDER BY i.normalized_name;
