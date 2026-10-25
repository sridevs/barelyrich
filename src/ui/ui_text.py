"""Editable UI text. Internal identifiers and domain validation stay in their own layers."""

from collections.abc import Iterable
from datetime import date

from src import config


# Workflow navigation and statement uploads.
DATA_ENTRY = "Data entry"
PORTFOLIO_OVERVIEW = "Portfolio overview"
PARSE_STATEMENT = "Parse statement"
MANUAL_VALUATION = "Manual valuation"
ACCOUNT_BALANCES = "Account balances"
STATEMENT_DESCRIPTION = "Extract currency balances from a local PDF statement."
OTHER_ASSETS = "Other assets and debts"
VALUATION_DESCRIPTION = "Record gold, property or other dated valuations."
SELECTED = "Selected"
CHOOSE_WORKFLOW = "Choose this workflow"
BATCH_CHANGED = "Statement or account details changed; extract a fresh preview."
STATEMENT_SAVED = "This statement has been saved."
REVIEW_STATEMENTS = "Review statements"
BACK = "Back"
NEXT = "Next"
SAVE_ALL_BALANCES = "Save all balances"
BATCH_CONFIRMATION = "I reviewed all remaining parsed statements and want to save their balances."
PARSE_WITH_AI = "Parse with AI"
ASSET_TYPE = "Asset type"
ASSET_TYPE_HELP = "Choose liability for amounts owed, such as loans or card balances."
DEBUG_OUTPUT = "Log raw model output for debugging (contains sensitive data)"
DEBUG_OUTPUT_HELP = (
    "Writes the model response to the terminal running Streamlit before validation, "
    "and the failure reason if validation fails. "
    "Does not log the PDF file or images. "
    "Redact names, account numbers, balances and other private details before sharing."
)
EXTRACT_BALANCES = "Extract balances"

# Account review.
REVIEW_BALANCES = "Review balances"
REVIEW_WARNING = (
    "AI values are not independently verified. Check the institution, account numbers, "
    "balances and dates against your PDF, then approve each account below."
)
ACCOUNT_UPDATES = "How account updates work"
ACCOUNT_UPDATES_HELP = (
    "Account numbers identify future statements even when aliases change. "
    "Current totals use only the latest statement's currency pockets. "
    "Legacy alias-only records are not merged automatically; avoid duplicates."
)
STATEMENT_INSTITUTION = "Statement institution"
INSTITUTION_HELP = (
    "Confirm the issuer, choose an existing institution, or type a new name. "
    "Use the same institution for future imports to keep account updates together."
)
ACCOUNT_TYPE = "Account type"
ACCOUNT_TYPE_HELP = "AI suggestion, not verified. Correct it or enter your own account type."
ACCOUNT_ALIAS = "Account alias"
ACCOUNT_ALIAS_HELP = (
    "Suggested from institution and type. Editable display label; account numbers identify updates."
)
SAVED = "Saved"
ACCOUNT_CONFIRMATION = "I reviewed every account and currency balance and want to save them."
SAVE_BALANCES = "Save balances"
AI_INTERPRETATION = "AI interpretation"
BALANCES_ALT = "Extracted currency balances for this account"
CLASSIFICATIONS_ALT = "Model-reported balance and date classifications"

# Manual valuations.
SAVE_VALUATION = "Save valuation"
VALUATION_GUIDANCE = (
    "Record gold, property, other assets, debts or an account without a statement. "
    "Enter your ownership share's total estimated market value in its currency, not "
    "quantity, purchase cost or a price per gram. Prices are not fetched automatically."
)
VALUATION_UPDATES = (
    "Reuse the same group and name for later valuations. The same date replaces its value; "
    "other dates build history. Enter zero when an asset is sold or a debt is repaid. "
    "Record property at gross value and its mortgage separately as a debt. "
    "Do not manually duplicate an account already imported from a statement."
)
ASSET_GROUP = "Institution or asset group"
PERSONAL_ASSETS = "Personal assets"
ASSET_NAME = "Asset or debt name"
ASSET_NAME_PLACEHOLDER = "Gold, home, overseas savings"
VALUATION_KIND = "Valuation kind"
VALUATION_CURRENCY = "Valuation currency"
TOTAL_VALUE = "Total value"
AMOUNT_PLACEHOLDER = "250000.00"
VALUE_AS_OF = "Value as of"
VALUATION_SAVED = "Saved valuation."

# Portfolio overview and history.
DISPLAY_CURRENCY = "Display currency"
VALUATION_DATE = "Valuation date"
SELECT_VALUATION_DATE = "Select a valuation date."
DATED_OBSERVATIONS_HELP = "Uses the latest balance and FX observation on or before this date."
PORTFOLIO_TAGLINE = "Keep tabs on your wealth. Keep your data to yourself."
STORAGE_WARNING = (
    "Real balances are stored in an unencrypted local SQLite database. Use FileVault "
    "and test encrypted backup/restore before adding sensitive records."
)
RECORDED_WEALTH = "Consolidated recorded wealth"
NO_WEALTH = "No recorded wealth yet. Parse a statement or add a manual asset/debt valuation in Data entry."
BALANCE_HISTORY = "Recorded balance history"
NET_WORTH_HISTORY = "Net worth over time"
NO_HISTORY = "No recorded wealth history yet."
HISTORY_GUIDANCE = (
    "Each point uses the latest recorded account, asset and debt valuations on or before "
    "that date, with dated FX. Values carry forward until updated; this is wealth history, "
    "not spending or investment performance."
)
HISTORY_ALT = "Historical net worth using dated account balances and exchange rates"

# Display column names and chart titles; storage keys and chart field IDs are separate.
INSTITUTION = "Institution"
ACCOUNT = "Account"
KIND = "Kind"
CURRENCY = "Currency"
BALANCE_DATE = "Balance date"
ACCOUNT_NUMBER = "Account number"
BALANCE = "Balance"
SOURCE = "Source"
RECORDED_AT = "Recorded / fetched (UTC)"
FX_DATE = "Oldest FX date used"
BALANCE_TYPE = "Balance type"
SCOPE = "Scope"
DATE_TYPE = "Date type"
DATE = "Date"
YEAR = "Year"


def statement_guidance() -> str:
    return (
        f"Upload PDFs (up to {config.MAX_VISION_PAGES} pages each) to extract balances for "
        "all identified accounts and currencies, not transactions. "
        "AI runs locally; your statement stays on this computer. "
        "Review each account and every balance before saving."
    )


def statement_upload_label() -> str:
    return f"Statement files (PDF, up to {config.MAX_STATEMENT_BYTES / 1_000_000:g} MB each)"


def batch_status(saved: int, pending: int, failed: int) -> str:
    return f"{saved} saved · {pending} pending · {failed} failed"


def statement_position(position: int, total: int) -> str:
    return f"**Statement {position} of {total}**"


def batch_save_guidance(pending: int) -> str:
    return (
        f"Save {pending} remaining parsed statements together using their current aliases "
        "and institutions. Failed and already-saved statements are excluded."
    )


def batch_saved(count: int, pending: int) -> str:
    return f"Saved {count} currency balances from {pending} statements."


def parsing_statement(position: int, total: int, name: str) -> str:
    return f"Parsing statement {position} of {total}: {name}"


def account_heading(index: int, number: str) -> str:
    return f"**Account {index} · {number}**"


def statement_date(as_of: date) -> str:
    return f"Statement date: {as_of.isoformat()}"


def account_confirmation(single: bool, index: int) -> str:
    return ACCOUNT_CONFIRMATION if single else f"I reviewed account {index} and want to save its balances."


def save_account_label(single: bool, index: int) -> str:
    return SAVE_BALANCES if single else f"Save account {index} balances"


def account_saved(count: int, single: bool, index: int) -> str:
    return (
        f"Saved {count} statement currency balances." if single else
        f"Saved {count} balances for account {index}."
    )


def currency_warning(currency: str, warning: str) -> str:
    return f"{currency}: {warning}"


def stale_accounts(accounts: Iterable[str]) -> str:
    return f"Balances more than {config.STALE_AFTER_DAYS} days old: " + ", ".join(accounts)


def stale_currencies(currencies: Iterable[str]) -> str:
    return f"FX rates more than {config.STALE_AFTER_DAYS} days old affect: " + ", ".join(currencies)


def valuation_summary(as_of: date) -> str:
    return (
        f"Valuation date: {as_of}. Latest known observations, not necessarily simultaneous "
        "or live. Only assets and debts you have recorded are included."
    )


def missing_fx(currencies: Iterable[str], base: str) -> str:
    return (
        "Total unavailable: missing dated FX to convert " + ", ".join(currencies)
        + f" to {base}. No partial total is shown."
    )


def recorded_net_worth(currency: str) -> str:
    return f"Recorded net worth ({currency})"


def net_worth(currency: str) -> str:
    return f"Net worth ({currency})"


def net_value(currency: str) -> str:
    return f"Net value ({currency})"


def fx_to(currency: str) -> str:
    return f"FX to {currency}"


def historical_chart_error(error: Exception) -> str:
    return f"Historical chart unavailable: {error}"


def fx_refresh_error(error: Exception) -> str:
    return (
        f"{error} Using saved dated rates where available; they may be out of date. "
        "Totals remain unavailable if a required rate has never been saved."
    )


def fx_refreshed(published_dates: str) -> str:
    return (
        f"FX refreshed automatically from Frankfurter. Published rate dates: {published_dates}. "
        "Daily reference rates, not real-time trading quotes."
    )


def history_hover(as_of: date, currency: str, amount: str | None) -> str:
    return f"{as_of:%d %b %Y} | {currency} {amount}"
