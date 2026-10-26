# BarelyRich

A local-first wealth tracker for recording assets and debts, viewing net worth,
and tracking its history across currencies.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,statements,local-model]"
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open http://127.0.0.1:8501. Keep the app on loopback; it has no authentication.
The portfolio starts empty and is stored in `data/portfolio.sqlite3`.
Set `WT_DATA_DIR` to use another data directory.

## Record wealth

Use **Parse statement** to extract balances from PDFs, or **Manual valuation**
for assets, debts, and accounts without usable statements. Review extracted
values against the original document; nothing is saved until you confirm.
Statement data is model-reported and may be incomplete or incorrect.

Manual valuations record your ownership share's total value, not quantity or
purchase price. Record a property's mortgage separately as a debt. Reuse the
same group and name to update a valuation; dated updates preserve history.

The overview shows valuations, net worth, and history in INR or SGD. Values
carry forward until updated. FX rates come from
[Frankfurter](https://frankfurter.dev/); historical values use historical rates.
Unconverted currencies are excluded from totals, and stale values or rates are
flagged.

## Local statement models

Download the models before extracting statements:

```bash
hf download Qwen/Qwen3-4B-Instruct-2507 --include "*.safetensors" --include "*.json" --include "*.txt" --include "*.model" --include "*.jinja"
hf download Qwen/Qwen3-VL-8B-Instruct --include "*.safetensors" --include "*.json" --include "*.txt" --include "*.model" --include "*.jinja"
```

For password-protected PDFs, the app requests the opening password only during
that import and clears it after use.
PDF text is processed first with Qwen3-4B. Scanned pages and incomplete text
extraction use Qwen3-VL-8B. Models run locally through Transformers; GGUF is
not supported. The app accepts PDFs up to 10 MB and 100 pages. Large statements
may still exceed the 100,000-input-token budget, the model's context capacity,
or available memory. Allow ample RAM
(32 GB or more recommended for the default vision model).

| Setting | Purpose |
| --- | --- |
| `WT_TEXT_MODEL` | Text model ID or local directory |
| `WT_TRANSFORMERS_MODEL` | Vision model ID or local directory |
| `WT_TRANSFORMERS_DEVICE` | `auto`, `mps`, `cuda`, or `cpu` |
| `WT_TRANSFORMERS_MAX_NEW_TOKENS` | Output limit (default 8,192; maximum 32,768) |
| `WT_DATA_DIR` | Portfolio data directory |

## Privacy and backups

PDFs and model inference stay on your computer. Only currency codes and dates
are sent to Frankfurter. SQLite is not encrypted; use FileVault or an encrypted
volume to protect sensitive data. The app has no authentication as its fully local.

Create and restore encrypted backups with:

```bash
python -m src.backup create data/portfolio.sqlite3 backups/portfolio.enc
python -m src.backup restore backups/portfolio.enc data/portfolio-restored.sqlite3
```

Stop the app before backing up. Commands prompt for a passphrase; store it
separately and test restoring to a different file.

## Development

Run tests:

```bash
python -m pytest -q
```

Focused UI and integration tests:

```bash
python -m pytest --no-cov tests/ui tests/integration -q
```

The app uses Python package `src`; domain rules live in `src/models`, SQLite
access in `src/repo`, and the Streamlit UI in `src/ui`.
