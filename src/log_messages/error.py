"""Error wording; defining text here does not automatically log exceptions."""

# Local statement model adapter.
LOCAL_INFERENCE_TEXT_ONLY = "Local statement inference supports text output without tools only."
NO_STATEMENT = "The text model returned no statement data."

# agents.
MISSING_REQUIRED_FIELDS = 'Missing required fields.'
MODEL_RETURNED_AN_INVALID_OR_OVERSIZED_RESPONSE = 'Model returned an invalid or oversized response.'
REQUIRED_STATEMENT_DATA_IS_MISSING_FROM_TEXT_OUTPUT = 'Required statement data is missing from text output.'
DUPLICATE_CURRENCY_RETRY_FEEDBACK = 'Multiple distinct balances for the same currency were returned. Return one native closing/current balance per currency for this account. Prefer its account-detail section over overview totals; exclude converted equivalents. Do not combine different amounts or accounts.'

# Backup and retry infrastructure.
PASSPHRASE_MUST_NOT_BE_EMPTY = 'Passphrase must not be empty'
UNRECOGNISED_BACKUP_FORMAT = 'Unrecognised backup format'
WRONG_PASSPHRASE_OR_DAMAGED_BACKUP = 'Wrong passphrase or damaged backup'
DATABASE_INTEGRITY_CHECK_FAILED = 'Database integrity check failed'
INVALID_RETRY_POLICY = 'Retry attempts must be positive and delay must be nonnegative.'
RETRY_ATTEMPTS_EXHAUSTED_WITHOUT_A_RESULT_OR_EXCEPTION = 'Retry attempts exhausted without a result or exception.'

# documents.
PDF_DEPENDENCY_REQUIRED = 'PDF {mode} requires the statements extra; install `pip install -e ".[statements]"`.'
PDF_PAGE_DIMENSIONS_MUST_BE_FINITE_AND_POSITIVE = 'PDF page dimensions must be finite and positive.'
RENDERED_IMAGE_TOO_LARGE = 'Rendered PDF page exceeds the {max_image_megabytes:g} MB image limit.'
PDF_OPERATION_FAILED = 'Unable to {operation} this PDF statement.'
STATEMENT_PAGE_LIMIT = 'Statement extraction supports at most {max_vision_pages} pages.'
PDF_PILLOW_REQUIRED = 'PDF images require Pillow; install `pip install -e ".[statements]"`.'
PASSWORD_PROTECTED_PDF = 'This PDF requires an opening password.'
INCORRECT_STATEMENT_PASSWORD = (
    'The password was incorrect, or this encrypted PDF could not be opened. '
    'Check the password and try again.'
)
STATEMENT_PDF_TEXT_EXCEEDS_THE_256_000_CHARACTER_LIMIT = 'Statement PDF text exceeds the 256,000-character limit.'
VISUAL_STATEMENT_PAGE_LIMIT = 'Visual statement extraction supports at most {max_vision_pages} pages. Upload a shorter statement containing all currency balances and its date.'
STATEMENT_FILE_TOO_LARGE = 'Statement file must be no larger than {max_statement_megabytes:g} MB.'
UPLOAD_A_PDF_STATEMENT = 'Upload a PDF statement.'

# inference.
MODEL_NAME_MUST_NOT_BE_BLANK = 'Model name must not be blank.'
MODEL_DEPENDENCY_REQUIRED = 'Loading {model_name!r} requires an unavailable model dependency. Install the complete local-model extra with `pip install -e ".[local-model]"`, including a torchvision version compatible with PyTorch. Vision AutoProcessor implementations may require torchvision even for image-only input.'
LOCAL_MODEL_FILES_UNAVAILABLE = 'Could not load {model_name!r} from local model files. Place the model in the Hugging Face cache or set {setting} to a local model directory; this runtime does not download models. Gated models require repository approval and Hugging Face authentication before downloading.'
LOCAL_INFERENCE_DEPENDENCIES_REQUIRED = "Local statement inference requires PyTorch and Transformers. Install the project's compatible PyTorch and Transformers dependencies first."
CUDA_UNAVAILABLE = 'WT_TRANSFORMERS_DEVICE=cuda was requested, but CUDA is unavailable.'
MPS_UNAVAILABLE = 'WT_TRANSFORMERS_DEVICE=mps was requested, but Apple Metal is unavailable.'
TRANSFORMERS_MODEL_SUPPORT_REQUIRED = 'Local statement inference requires Transformers with Qwen3-VL and Qwen3 support. Install the local-model extra (Transformers >=5.17).'
MODEL_LOADING_OUT_OF_MEMORY = 'The local model could not fit in device memory while loading. Try WT_TRANSFORMERS_DEVICE=cpu or use a smaller local model.'
VISUAL_INFERENCE_PAGE_LIMIT = 'Visual inference supports at most {max_vision_pages} page images.'
STATEMENT_IMAGE_PILLOW_REQUIRED = 'Statement page images require Pillow; install the project\'s "statements" extra.'
A_STATEMENT_PAGE_IMAGE_HAS_INVALID_DIMENSIONS = 'A statement page image has invalid dimensions.'
STATEMENT_IMAGE_PIXEL_LIMIT = 'A statement page image has {pixel_count} pixels, exceeding the {max_image_pixels}-pixel limit.'
STATEMENT_IMAGE_UNSAFE_TO_DECODE = "A statement page image exceeds Pillow's safe decoding limit."
A_STATEMENT_PAGE_CONTAINS_AN_UNREADABLE_IMAGE = 'A statement page contains an unreadable image.'
INVALID_RUNTIME_CONFIGURATION = 'configuration must be a TransformersRuntimeConfig.'
STATEMENT_DOCUMENT_REQUIRED = 'Transformers inference requires a StatementDocument.'
THE_STATEMENT_EXTRACTION_PROMPT_MUST_NOT_BE_EMPTY = 'The statement extraction prompt must not be empty.'
THE_TEXT_MODEL_REQUIRES_EXTRACTED_TEXT_NOT_PAGE_IMAGES = 'The text model requires extracted text, not page images.'
MODEL_GENERATION_BUSY = 'The local statement model is already generating another response. Retry shortly.'
MODEL_GENERATION_OUT_OF_MEMORY = 'The local model ran out of device memory while preparing or processing the statement. Try fewer pages or smaller images, or set WT_TRANSFORMERS_DEVICE=cpu.'
STATEMENT_INPUT_TOKEN_LIMIT = 'Statement input uses {input_token_count} tokens, exceeding the {max_input_tokens}-token limit. Upload fewer pages or reduce the statement text and image detail.'
THE_LOCAL_MODEL_RETURNED_AN_EMPTY_RESPONSE = 'The local model returned an empty response.'
MODEL_EOS_CONFIGURATION_REQUIRED = 'The local model must configure EOS token IDs to verify complete responses.'
MODEL_OUTPUT_TOKEN_LIMIT = 'The local model reached its output token limit; no partial response was accepted. Use a shorter statement or increase max_new_tokens.'
MODEL_RESPONSE_MISSING_EOS = 'The local model stopped without EOS, possibly after reaching its {max_time_seconds}-second generation time limit. No partial response was accepted. Retry with fewer pages.'
THE_LOCAL_MODEL_RETURNED_AN_INVALID_GENERATION_SHAPE = 'The local model returned an invalid generation shape.'
THE_LOCAL_MODEL_RETURNED_A_TRUNCATED_PROMPT = 'The local model returned a truncated prompt.'

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
ACCOUNT_ALIAS_MUST_CONTAIN_1_100_CHARACTERS = 'Account alias must contain 1-100 characters.'
KIND_MUST_BE_ASSET_OR_LIABILITY = 'Kind must be asset or liability.'
LIABILITIES_MUST_BE_ENTERED_AS_POSITIVE_AMOUNTS_OWED = 'Liabilities must be entered as positive amounts owed.'
INVALID_OBSERVATION_DATE = 'As-of date must be a date, not in the future.'
UNSUPPORTED_BALANCE_SOURCE = 'Unsupported balance source.'
REMOVE_LEADING_OR_TRAILING_WHITESPACE_FROM_THE_ACCOUNT_ALIAS = 'Remove leading or trailing whitespace from the account alias.'
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
STATEMENT_ACCOUNT_BALANCE_COUNT = 'Each statement account must contain between 1 and 30 balances.'
STATEMENT_BALANCES_MUST_BE_VALIDATED_BALANCE_OBJECTS = 'Statement balances must be validated balance objects.'
AMBIGUOUS_STATEMENT_CURRENCY = 'Multiple balances for the same currency are ambiguous within one account.'
INCONSISTENT_STATEMENT_ACCOUNT_DATE = 'All currency pockets of an account must share one statement date.'
ACCOUNT_ALIAS_IS_REQUIRED = 'Account alias is required.'
STATEMENT_BALANCE_MUST_BE_A_DECIMAL_VALUE = 'Statement balance must be a decimal value.'
STATEMENT_CURRENCY_MUST_BE_A_THREE_LETTER_CODE = 'Statement currency must be a three-letter code.'
STATEMENT_DATE_MUST_BE_A_DATE = 'Statement date must be a date.'
MODEL_RETURNED_AN_UNKNOWN_BALANCE_ROLE = 'Model returned an unknown balance role.'
MODEL_RETURNED_AN_UNKNOWN_ACCOUNT_SCOPE = 'Model returned an unknown account scope.'
MODEL_RETURNED_AN_UNKNOWN_DATE_ROLE = 'Model returned an unknown date role.'
STATEMENT_REFERS_TO_A_MISSING_PAGE = 'Statement refers to a missing page.'
STATEMENT_CONTAINS_NO_PAGES = 'Statement contains no pages.'
STATEMENT_PAGES_MUST_HAVE_UNIQUE_INCREASING_PAGE_NUMBERS = 'Statement pages must have unique, increasing page numbers.'
STATEMENT_ACCOUNT_COUNT = 'A statement must contain between 1 and 30 identified accounts.'
STATEMENT_ACCOUNTS_MUST_BE_VALIDATED_ACCOUNT_OBJECTS = 'Statement accounts must be validated account objects.'
STATEMENT_OUTPUT_CONTAINS_A_REPEATED_ACCOUNT_NUMBER = 'Statement output contains a repeated account number.'
A_STATEMENT_MUST_CONTAIN_AT_MOST_30_CURRENCY_BALANCES = 'A statement must contain at most 30 currency balances.'
AN_ACCOUNT_ALIAS_IS_REQUIRED_FOR_EVERY_STATEMENT_ACCOUNT = 'An account alias is required for every statement account.'
STATEMENT_PAGE_NUMBERS_MUST_BE_POSITIVE_INTEGERS = 'Statement page numbers must be positive integers.'
STATEMENT_PAGE_IMAGE_BYTE_LIMIT = 'Statement page image must contain at most {max_image_megabytes:g} MB of image bytes.'

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
INSTITUTION_MIGRATION_CONFLICT = 'Cannot migrate institution {record_key!r}: its normalized name conflicts with another institution. Existing accounts were not changed.'
ACCOUNT_MIGRATION_WOULD_BREAK_EXISTING_REFERENCES = 'Account migration would break existing references.'
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
STATEMENT_IMPORT_REQUIRES_A_STATEMENT_SOURCED_BALANCE = 'Statement import requires a statement-sourced balance.'
STATEMENT_IMPORT_REQUIRES_STATEMENT_SOURCED_BALANCES = 'Statement import requires statement-sourced balances.'
HISTORICAL_NET_WORTH_UNAVAILABLE = 'Net worth history is unavailable for {day}: missing balances or dated FX.'
STATEMENT_INSTITUTION_MISSING_NO_SAVE = 'AI could not identify the statement institution. No balances were saved.'

DISPLAY_CURRENCY_REQUIRED = "Display currency must be {currencies}."
STATEMENT_VALIDATION_EXHAUSTED = (
    "Model did not return a valid statement after four attempts "
    "(three corrections); JSON/schema or financial validation failed; "
    "no balances were saved."
)
LAST_FINANCIAL_ISSUE = " Last financial issue: {issue}"
DOMAIN_RETRY_FEEDBACK = (
    "Statement financial validation failed. Re-read the original document and "
    "check the account, currency pockets and observation dates."
)
MISSING_STATEMENT_PREVIEW = "A statement preview is missing. Extract a fresh batch before saving."
