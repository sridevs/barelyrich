"""Informational log templates with lazy logging placeholders."""

# Document preparation and extraction routing.
PDF_TEXT_EXTRACTION = "Statement phase: PDF parser - extracting embedded text."
PDF_TEXT_AVAILABLE = "PDF parser: embedded text available on all %d pages."
DOCUMENT_PROCESSED = "Statement document processing completed in %.2fs (pages=%d)"

# Model lifecycle and output validation.
GENERATION_STARTED = "Statement generation: %s, attempt=%d started."
GENERATION_DIAGNOSTICS = (
    "Generation diagnostics: input_tokens=%s, generated_tokens=%s, "
    "elapsed_seconds=%.2f, first_token_seconds=%s, decode_tokens_per_second=%.2f, eos=%s"
)
OUTPUT_VALIDATION = "Statement phase: output validation (%s, attempt=%d)."
EQUIVALENT_BALANCES_COLLAPSED = (
    "Statement normalization: repeated equivalent balance rows collapsed for review "
    "(rows=%d, unique=%d)."
)
PREVIEW_READY = "Statement phase: preview ready for human review; no balances saved."
INFERENCE_FINISHED = "Local statement inference finished in %.2fs (pages=%d)"
FIELD_REPAIR_STARTED = "Repairing %d rejected scalar fields; preserving other statement fields."
FIELD_REPAIR_FINISHED = "Targeted field correction passed schema and financial validation."
ROW_REPAIR_STARTED = "Repairing %d rejected financial rows; preserving all other rows."
ROW_REPAIR_FINISHED = "Targeted row correction passed schema and financial validation."
CURRENCY_ACCOUNT_SECTIONS_MERGED = (
    "Statement normalization: merged currency account sections (%s sections, %s accounts)."
)
CHUNK_EXTRACTION = "Statement chunk extraction: pages=%s (%s/%s)"
