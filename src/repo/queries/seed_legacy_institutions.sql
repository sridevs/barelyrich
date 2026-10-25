INSERT INTO institutions(key,name,normalized_name,country_code,account_type) VALUES
('dbs_sg','DBS Singapore','dbs singapore','SG','bank'),
('uob_sg','UOB Singapore','uob singapore','SG','bank'),
('tiger_sg','Tiger Brokers Singapore','tiger brokers singapore','SG','brokerage'),
('hdfc_in','HDFC Bank','hdfc bank','IN','bank'),
('kotak_in','Kotak Mahindra Bank','kotak mahindra bank','IN','bank')
ON CONFLICT DO NOTHING;
