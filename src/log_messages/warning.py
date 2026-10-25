"""Warning log templates; sensitive output still requires caller opt-in."""

SENSITIVE_MODEL_OUTPUT = "Statement model output BEFORE validation (sensitive; JSON-encoded): %s"
OUTPUT_RETRY = (
    "Statement output validation failed. Retrying with "
    "the original local document; no balances were saved. Errors: %s"
)
VALIDATION_FAILED = "Statement validation failed: %s"
FINANCIAL_CORRECTION = "Statement financial correction: %s"
OPERATION_RETRY = "%s failed with %s; retrying attempt %d/%d in %.1fs."

# Review diagnostics are returned to the UI, not automatically logged.
BALANCE_ROLE_REVIEW = (
    "AI classified this amount as {role}; "
    "verify that it is the balance you intend to track."
)
ACCOUNT_SCOPE_REVIEW = (
    "AI did not identify this as a single-account balance. "
    "Check for aggregate totals and double-counting before confirming."
)
DATE_ROLE_REVIEW = (
    "AI classified the date as {role}; "
    "verify the observation date before confirming."
)
