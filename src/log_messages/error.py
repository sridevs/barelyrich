"""Error wording; defining text here does not automatically log exceptions."""

INVALID_POSITIONAL_ROW = (
    "Each balance row must contain exactly six positions: "
    "as_of, balance, currency, withdrawal, deposit, description."
)

INVALID_TRANSACTION_MOVEMENT = (
    "Withdrawals and deposits must be nonnegative decimals, with transaction "
    "identity present when movement fields are provided."
)
INVALID_TRANSACTION_ORDER = "Transaction row numbers must be positive integers and unique per account."
INVALID_TRANSACTION_DESCRIPTION = "Transaction descriptions must be text of at most 2000 characters."
STATEMENT_TRANSACTION_LIMIT = "A statement supports at most 10000 balance and transaction rows."

# Local statement model adapter.
LOCAL_INFERENCE_TEXT_ONLY = "Local statement inference supports text output without tools only."
NO_STATEMENT = "The text model returned no statement data."

# agents.
MISSING_REQUIRED_FIELDS = 'Missing required fields.'
MODEL_RETURNED_AN_INVALID_OR_OVERSIZED_RESPONSE = 'Model returned an invalid or oversized response.'
REQUIRED_STATEMENT_DATA_IS_MISSING_FROM_TEXT_OUTPUT = 'Required statement data is missing from text output.'
DUPLICATE_CURRENCY_RETRY_FEEDBACK = 'Conflicting snapshots for the same currency and date were returned. Return one native closing/current snapshot per currency and date. Keep every transaction in ledger array order with its movements and running balance. Prefer account-detail sections over overview totals; exclude converted equivalents. Do not combine different amounts or accounts.'

# Backup and retry infrastructure.
PASSPHRASE_MUST_NOT_BE_EMPTY = 'Passphrase must not be empty'
UNRECOGNISED_BACKUP_FORMAT = 'Unrecognised backup format'
WRONG_PASSPHRASE_OR_DAMAGED_BACKUP = 'Wrong passphrase or damaged backup'
DATABASE_INTEGRITY_CHECK_FAILED = 'Database integrity check failed'
INVALID_RETRY_POLICY = 'Retry attempts must be positive and delay must be nonnegative.'
RETRY_ATTEMPTS_EXHAUSTED_WITHOUT_A_RESULT_OR_EXCEPTION = 'Retry attempts exhausted without a result or exception.'

# readers.
PDF_DEPENDENCY_REQUIRED = 'PDF {mode} requires the statements extra; install `pip install -e ".[statements]"`.'
PDF_OPERATION_FAILED = 'Unable to {operation} this PDF statement.'
STATEMENT_PDF_LAYOUT_TOO_LARGE = 'This PDF has invalid or excessively large page dimensions for text layout extraction.'
STATEMENT_PAGE_LIMIT = 'Statement extraction supports at most {max_statement_pages} pages.'
PASSWORD_PROTECTED_PDF = 'This PDF requires an opening password.'
INCORRECT_STATEMENT_PASSWORD = (
    'The password was incorrect, or this encrypted PDF could not be opened. '
    'Check the password and try again.'
)
STATEMENT_PDF_TEXT_EXCEEDS_THE_256_000_CHARACTER_LIMIT = 'Statement PDF text exceeds the 256,000-character limit.'
STATEMENT_FILE_TOO_LARGE = 'Statement file must be no larger than {max_statement_megabytes:g} MB.'
UPLOAD_A_SUPPORTED_STATEMENT = 'Upload a PDF or CSV statement.'
CSV_ENCODING_REQUIRED = 'CSV statements must use UTF-8 encoding.'
CSV_STATEMENT_EMPTY = 'The CSV statement is empty.'
CSV_STATEMENT_TEXT_TOO_LARGE = (
    'CSV statement text exceeds the {max_characters}-character limit.'
)
CSV_RECORD_TOO_LARGE = 'A CSV record and its header exceed the 12,000-character chunk limit. Shorten the record or header and retry.'
CSV_INVALID_RECORD = 'The CSV statement contains invalid quoting. Check quoted fields and retry.'
STATEMENT_PAGE_RECORD_COUNT_INVALID = 'Statement page record count must be a non-negative integer.'
TRANSACTION_COUNT_MISMATCH_RETRY_FEEDBACK = (
    'The target CSV rows contain exactly {expected} transaction records, but you returned {actual} '
    'transactions. Return exactly one transaction per target data row: never summarize, merge, skip, '
    'or invent rows, and do not copy rows from context.'
)

# inference.
FIELD_REPAIR_FAILED = (
    "Targeted field correction failed full validation. No partial statement was accepted. "
    "Check the source document and retry extraction."
)
OLLAMA_CONTEXT_TOO_SMALL = "Ollama context must exceed the output token allowance."
OLLAMA_CONNECTION_UNAVAILABLE = "Could not connect to local Ollama."
OLLAMA_HTTP_FAILURE = (
    "Local Ollama returned HTTP {status}. Check that {model_name!r} "
    "is installed with `ollama list`."
)
OLLAMA_MODEL_LIST_HTTP_FAILURE = "Local Ollama returned HTTP {status} while listing installed models."
OLLAMA_MODEL_LIST_INVALID = "Local Ollama returned an invalid installed-model list."
OLLAMA_MODEL_LIST_OVERSIZED = "Local Ollama returned an oversized installed-model list."
OLLAMA_CONNECTION_FAILURE = (
    "Local Ollama connection failed or exceeded the {seconds}-second limit. "
    "Check that Ollama is running on 127.0.0.1:11434. No partial response was accepted."
)
OLLAMA_INCOMPLETE_STREAM = (
    "Ollama stream ended without completion. No partial response was accepted."
)
OLLAMA_INVALID_EVENT = "Ollama returned an invalid stream event."
OLLAMA_INFERENCE_FAILURE = "Ollama reported an inference error. Check the local Ollama server."
OLLAMA_UNEXPECTED_THINKING = (
    "Ollama generated thinking despite think=false; use a non-thinking model."
)
OLLAMA_HTTP_ERROR_DETAIL = "Local Ollama returned HTTP {status}: {detail}"
OLLAMA_GENERATION_DEADLINE_EXCEEDED = "Ollama generation deadline exceeded."
OLLAMA_ABNORMAL_STOP = (
    "Ollama stopped without a normal completion. No partial response was accepted."
)
OLLAMA_MISSING_COUNTS = "Ollama omitted token counts; completion could not be verified."
OLLAMA_INPUT_TOO_LARGE = (
    "Ollama input leaves insufficient context for the output allowance. Use fewer pages."
)
MODEL_NAME_MUST_NOT_BE_BLANK = 'Model name must not be blank.'
THE_STATEMENT_EXTRACTION_PROMPT_MUST_NOT_BE_EMPTY = 'The statement extraction prompt must not be empty.'
STATEMENT_PDF_TEXT_REQUIRED = (
    'This PDF has no readable text on one or more pages. Scanned statements are not '
    'supported. Run OCR on the PDF or upload a text-based statement.'
)
THE_LOCAL_MODEL_RETURNED_AN_EMPTY_RESPONSE = 'The local model returned an empty response.'
MODEL_OUTPUT_TOKEN_LIMIT = 'The local model reached its output token limit; no partial response was accepted. Use a shorter statement or increase max_new_tokens.'

# models.
CURRENCY_MUST_BE_A_VALID_ISO_4217_CODE = 'Currency must be a valid ISO 4217 code.'

# models / entry.
A_STATEMENT_REVIEW_MUST_IDENTIFY_ITS_UPLOADED_FILE = 'A statement review must identify its uploaded file.'
AI_COULD_NOT_IDENTIFY_THE_STATEMENT_INSTITUTION = 'AI could not identify the statement institution.'
STATEMENT_ACCOUNT_WAS_NOT_FOUND_IN_THE_EXTRACTION = 'Statement account was not found in the extraction.'
REQUIRED_FIELD = '{label} is required.'
DATE_SELECTION_REQUIRED = 'Select {label}.'

# models / portfolio.
A_PORTFOLIO_ACCOUNT_HAS_NO_EXCHANGE_RATE = 'A portfolio account has no exchange rate.'
ACCOUNT_CURRENCY_OR_KIND_CHANGED = "An existing account's currency or kind cannot change. Use a different alias for a different account or currency."
ACCOUNT_ALIAS_MUST_CONTAIN_1_100_CHARACTERS = 'Account name must contain 1-100 characters.'
KIND_MUST_BE_ASSET_OR_LIABILITY = 'Kind must be asset or liability.'
LIABILITIES_MUST_BE_ENTERED_AS_POSITIVE_AMOUNTS_OWED = 'Liabilities must be entered as positive amounts owed.'
INVALID_OBSERVATION_DATE = 'As-of date must be a date, not in the future.'
UNSUPPORTED_BALANCE_SOURCE = 'Unsupported balance source.'
REMOVE_LEADING_OR_TRAILING_WHITESPACE_FROM_THE_ACCOUNT_ALIAS = 'Remove leading or trailing whitespace from the account name.'
INVALID_FX_RATE = 'FX rate must be positive; INR to INR must equal 1.'
INSTITUTION_ACCOUNT_TYPE_MUST_BE_BANK_BROKERAGE_OR_OTHER = 'Institution account type must be bank, brokerage or other.'
PORTFOLIO_HAS_NO_ACCOUNT_BALANCES = 'Portfolio has no account balances.'
INSTITUTION_NAME_MUST_BE_TEXT = 'Institution name must be text.'
INSTITUTION_NAME_MUST_NOT_CONTAIN_CONTROL_CHARACTERS = 'Institution name must not contain control characters.'
INSTITUTION_NAME_LENGTH = 'Institution name must contain 1-{max_length} characters.'
DECIMAL_MAGNITUDE_LIMIT = '{label} must be finite and no larger than 1e18 in magnitude.'
DECIMAL_PRECISION_LIMIT = '{label} supports at most eight decimal places.'
INSTITUTION_COUNTRY_MUST_BE_A_TWO_LETTER_UPPERCASE_CODE = 'Institution country must be a two-letter uppercase code.'
INVALID_CURRENCY_CODE = 'Currency must be a three-letter uppercase code, e.g. SGD or INR.'
STATEMENT_ACCOUNT_NUMBER_MUST_CONTAIN_1_100_CHARACTERS = 'Statement account number must contain 1-100 characters.'
STATEMENT_ACCOUNT_NUMBER_MUST_NOT_CONTAIN_CONTROL_CHARACTERS = 'Statement account number must not contain control characters.'
PRINTED_ACCOUNT_DIGITS_REQUIRED = 'Statement account number must include its printed digits, not a product name.'
INVALID_ACCOUNT_PRODUCT_TYPE = 'Account type must be text of at most 100 characters.'
ACCOUNT_TYPE_MUST_NOT_CONTAIN_CONTROL_CHARACTERS = 'Account type must not contain control characters.'
INVALID_OR_FUTURE_ISO_DATE = 'As-of date must be YYYY-MM-DD and cannot be in the future.'
DECIMAL_REQUIRED = '{label} must be a decimal number.'
AS_OF_DATE_MUST_BE_YYYY_MM_DD = 'As-of date must be YYYY-MM-DD.'

# models / statements.
STATEMENT_BALANCES_MUST_BE_VALIDATED_BALANCE_OBJECTS = 'Statement balances must be validated balance objects.'
ACCOUNT_ALIAS_IS_REQUIRED = 'Account name is required.'
STATEMENT_BALANCE_MUST_BE_A_DECIMAL_VALUE = 'Statement balance must be a decimal value.'
STATEMENT_CURRENCY_MUST_BE_A_THREE_LETTER_CODE = 'Statement currency must be a three-letter code.'
STATEMENT_DATE_MUST_BE_A_DATE = 'Statement date must be a date.'
STATEMENT_REFERS_TO_A_MISSING_PAGE = 'Statement refers to a missing page.'
STATEMENT_CONTAINS_NO_PAGES = 'Statement contains no pages.'
STATEMENT_PAGES_MUST_HAVE_UNIQUE_INCREASING_PAGE_NUMBERS = 'Statement pages must have unique, increasing page numbers.'
STATEMENT_ACCOUNT_COUNT = 'A statement must contain between 1 and 30 identified accounts.'
STATEMENT_ACCOUNTS_MUST_BE_VALIDATED_ACCOUNT_OBJECTS = 'Statement accounts must be validated account objects.'
STATEMENT_OUTPUT_CONTAINS_A_REPEATED_ACCOUNT_NUMBER = 'Statement output contains a repeated account number.'
RESOLVE_STATEMENT_SUMMARIES = (
    'Multiple balance summaries share a currency and date. Edit extracted rows to keep '
    'one correct closing balance per currency/date before saving.'
)
A_STATEMENT_MUST_CONTAIN_AT_MOST_30_CURRENCY_BALANCES = 'A statement must contain at most 30 currency balances.'
AN_ACCOUNT_ALIAS_IS_REQUIRED_FOR_EVERY_STATEMENT_ACCOUNT = 'An account name is required for every statement account.'
STATEMENT_PAGE_NUMBERS_MUST_BE_POSITIVE_INTEGERS = 'Statement page numbers must be positive integers.'
STATEMENT_PAGE_TEXT_REQUIRED = 'Statement page must contain extracted text.'

# providers.
EXCHANGE_RATE_MUST_BE_A_FINITE_POSITIVE_NUMBER = 'Exchange rate must be a finite positive number.'
EXCHANGE_RATE_SERVICE_RETURNED_AN_OVERSIZED_RESPONSE = 'Exchange-rate service returned an oversized response.'
EXPECTED_A_LIST_OF_EXCHANGE_RATES = 'Expected a list of exchange rates.'
THE_SERVICE_DID_NOT_PROVIDE_EVERY_REQUIRED_CURRENCY = 'The service did not provide every required currency.'
UNEXPECTED_EXCHANGE_RATE_BASE_CURRENCY = 'Unexpected exchange-rate base currency.'
EXCHANGE_RATE_DATE_IS_LATER_THAN_THE_VALUATION_DATE = 'Exchange-rate date is later than the valuation date.'
FX_SERVICE_UNAVAILABLE = 'Automatic FX refresh failed: the exchange-rate service is unavailable.'
FX_RESPONSE_INVALID = 'Automatic FX refresh failed: invalid or incomplete exchange-rate data.'
UNEXPECTED_OR_DUPLICATE_EXCHANGE_RATE_CURRENCY = 'Unexpected or duplicate exchange-rate currency.'

# repo.
STATEMENT_EDIT_REQUIRED_FIELDS = "Every row requires a date, currency and balance."
STATEMENT_EDIT_EMPTY_ACCOUNT = "Keep at least one row in this account, or cancel corrections."
STATEMENT_EDIT_PENDING = "Apply or cancel account corrections before saving."
STATEMENT_EDIT_SAVED = "Saved accounts cannot be edited in this review."
STATEMENT_EDIT_NOT_STARTED = "Start editing this account before applying corrections."
FUTURE_HISTORICAL_FX_DATE = 'Historical FX publication date must not follow the requested date.'
DATED_INR_RATE_MISSING = 'No dated INR exchange rate for {currency} on {as_of}.'
DUPLICATE_IMPORT_ACCOUNT_DATE = 'Duplicate account/date in one import; provide each account currency only once.'
INSTITUTION_IDENTITY_CONFLICTS_WITH_AN_EXISTING_RECORD = 'Institution identity conflicts with an existing record.'
NO_ACCOUNT_BALANCES_WERE_PROVIDED = 'No account balances were provided.'

# repo / queries.
INVALID_SQL_RESOURCE_NAME = 'Invalid SQL resource name: {name!r}'
SQL_RESOURCE_IS_EMPTY_SQL = 'SQL resource is empty: {name}.sql'
SQL_RESOURCE_NOT_FOUND_SQL = 'SQL resource not found: {name}.sql'

# service.
HISTORICAL_FX_REFRESH_RETURNED_INCOMPLETE_OR_FUTURE_RATES = 'Historical FX refresh returned incomplete or future rates.'
STATEMENT_IMPORT_REQUIRES_STATEMENT_SOURCED_BALANCES = 'Statement import requires statement-sourced balances.'
HISTORICAL_NET_WORTH_UNAVAILABLE = 'Net worth history is unavailable for {day}: missing balances or dated FX.'
STATEMENT_INSTITUTION_MISSING_NO_SAVE = 'AI could not identify the statement institution. No balances were saved.'

DISPLAY_CURRENCY_REQUIRED = "Display currency must be {currencies}."
STATEMENT_VALIDATION_EXHAUSTED = (
    "Model did not return a valid statement after two attempts "
    "(three corrections); JSON/schema or financial validation failed; "
    "no balances were saved."
)
FINANCIAL_VALIDATION_RETRY = "{guidance}\nValidation error: {failure}"
LAST_FINANCIAL_ISSUE = " Last financial issue: {issue}"
DOMAIN_RETRY_FEEDBACK = (
    "Statement financial validation failed. Re-read the original document and "
    "check the account, currency pockets and observation dates."
)
MISSING_STATEMENT_PREVIEW = "A statement preview is missing. Extract a fresh batch before saving."
STATEMENT_TRANSACTION_MOVEMENT_REQUIRED = (
    "A transaction requires a printed withdrawal or deposit amount; both cannot be null. "
    "Copy the printed movement, or omit the row if it is an opening/closing balance summary. "
    "Never invent a zero to satisfy validation."
)
STATEMENT_CHUNK_FAILED = "Chunk pages {page_range} failed; no partial statement was saved. {failure}"
STATEMENT_CHUNK_INSTITUTION_CONFLICT = (
    "Chunk pages {page_range} returned a conflicting institution; review the source."
)
STATEMENT_BALANCE_FIELD_INVALID = "balances[{index}]: {failure}"
MERGED_STATEMENT_ACCOUNT_INVALID = "Merged accounts[{index}].{failure}"
STATEMENT_DRAFT_BALANCE_REQUIRED = "Enter a balance before applying corrections."
