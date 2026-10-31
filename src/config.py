"""Application defaults shared by the UI, services and adapters.

Keep protocol contracts, financial invariants and fictional fixtures in their
own modules. In particular, stored FX observations remain INR-denominated.
"""

import os
from pathlib import Path

PAGE_TITLE = "BarelyRich"
APP_TITLE = "BarelyRich"
PAGE_ICON = "📈"
PAGE_LAYOUT = "wide"

DISPLAY_CURRENCIES = ("INR", "SGD")
DEFAULT_DISPLAY_CURRENCY = DISPLAY_CURRENCIES[0]
STALE_AFTER_DAYS = 30
MONEY_DECIMAL_PLACES = 2

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PORTFOLIO_DATABASE = "portfolio.sqlite3"

MAX_STATEMENT_BYTES = 10_000_000
MAX_STATEMENT_TEXT_CHARACTERS = 256_000
STATEMENT_UPLOAD_MB = (MAX_STATEMENT_BYTES + 1024**2 - 1) // 1024**2
MAX_STATEMENT_PAGES = 100
MAX_RESPONSE_BYTES = 256_000

DEFAULT_OLLAMA_MODEL = "qwen3:4b-instruct"
DEFAULT_OLLAMA_CONTEXT_TOKENS = 40_960
DEFAULT_MAX_NEW_TOKENS = 16384
DEFAULT_MAX_TIME_SECONDS = 900

FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
FX_TIMEOUT_SECONDS = 30
MAX_FX_RESPONSE_BYTES = 100_000


def data_directory() -> Path:
    """Resolve environment overrides on each app run, not at module import."""
    return Path(os.environ.get("WT_DATA_DIR", DEFAULT_DATA_DIR))
