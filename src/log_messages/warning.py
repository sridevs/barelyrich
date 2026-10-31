"""Warning log templates; sensitive output still requires caller opt-in."""

SENSITIVE_MODEL_OUTPUT = "Statement model output BEFORE validation (sensitive; JSON-encoded): %s"
OUTPUT_RETRY = (
    "Statement output validation failed. Retrying with "
    "the original local document; no balances were saved. Errors: %s"
)
VALIDATION_FAILED = "Statement validation failed: %s"
FINANCIAL_CORRECTION = "Statement financial correction: %s"
OPERATION_RETRY = "%s failed with %s; retrying attempt %d/%d in %.1fs."
TARGETED_VALIDATION_FAILURE = "Statement validation rejected output: %s"
TARGETED_VALIDATION_OUTPUT = "SENSITIVE: Rejected statement/correction output (logging enabled): %s"
FIELD_REPAIR_FAILED = (
    "Targeted field correction failed full validation. No partial statement was accepted. "
    "Check the source document and retry extraction."
)
CONFLICTING_STATEMENT_ACCOUNT_TYPES = "Currency sections for the same account have conflicting account types."
