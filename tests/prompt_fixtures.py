"""Fictional extraction responses for tests, never sent to inference."""

STATEMENT_RESPONSE_EXAMPLE = {
    "institution": {"name": "Example Bank"},
    "accounts": [{
        "number": "****1234",
        "account_type": "Savings",
        "balances": [
            ["2025-09-29", "9.25", "SGD", "1.00", None, "Payment"],
            ["2025-09-30", "14.25", "SGD", None, "5.00", "Interest credit"],
        ],
    }],
}
