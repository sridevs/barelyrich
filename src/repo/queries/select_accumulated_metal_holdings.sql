WITH eligible_holdings AS (
 SELECT t.account_id, t.as_of, v.quantity, mp.metal, mp.purity, mp.currency, mp.unit
 FROM precious_metal_valuations v
 JOIN transactions t ON t.id=v.transaction_id
 JOIN precious_metal_prices mp ON mp.id=v.price_id
 WHERE t.as_of<=?
)
SELECT h.account_id, h.metal, h.purity, h.currency, h.unit, h.quantity,
 p.price, p.source, p.observed_at
FROM eligible_holdings h
JOIN precious_metal_prices p ON p.id=(
 SELECT latest.id FROM precious_metal_prices latest
 WHERE latest.metal=h.metal AND latest.purity=h.purity
  AND latest.currency=h.currency AND latest.unit=h.unit
  AND substr(latest.observed_at,1,10)<=?
 ORDER BY latest.observed_at DESC,latest.id DESC LIMIT 1
)
ORDER BY h.account_id,h.metal,h.purity,h.as_of;
