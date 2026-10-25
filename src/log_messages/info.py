"""Informational log templates with lazy logging placeholders."""

# Document preparation and extraction routing.
PDF_TEXT_EXTRACTION = "Statement phase: PDF parser - extracting embedded text."
PDF_TEXT_AVAILABLE = "PDF parser: embedded text available on all %d pages."
PDF_TEXT_MISSING = "PDF parser: a page has no text; using the vision path."
PDF_IMAGE_PREPARATION = "Statement phase: PDF renderer - preparing page images for vision."
DOCUMENT_PROCESSED = "Statement document processing completed in %.2fs (pages=%d)"
EXTRACTION_STARTED = "Statement phase: %s extraction (pages=%d)."
VISION_FALLBACK = "Vision fallback: required text output data is missing; rendering the full PDF."
VISION_EXTRACTION_STARTED = "Statement phase: vision model extraction (pages=%d)."

# Model lifecycle and output validation.
MODEL_LOADING = "Statement model: kind=%s, model=%s; loading/reusing local weights."
MODEL_INPUT_PREPARATION = "Statement phase: model input preparation."
TOKEN_GENERATION = "Statement phase: token generation (kind=%s, device=%s, input_tokens=%d)."
GENERATION_STARTED = "Statement generation: %s, attempt=%d started."
OUTPUT_VALIDATION = "Statement phase: output validation (%s, attempt=%d)."
EQUIVALENT_BALANCES_COLLAPSED = (
    "Statement normalization: repeated equivalent balance rows collapsed for review "
    "(rows=%d, unique=%d)."
)
PREVIEW_READY = "Statement phase: preview ready for human review; no balances saved."
INFERENCE_FINISHED = "Local statement inference finished in %.2fs (pages=%d)"
