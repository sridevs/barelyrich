# BarelyRich

A local-first wealth tracker. Record assets and debts, import bank statements
with a local AI model, and follow your net worth over time across currencies.

Everything runs on your computer. Nothing is saved until you review and confirm it.

## Quick start

1. Install [Ollama](https://ollama.com) (0.35.1+) and pull the default model:

   ```bash
   ollama pull qwen3:4b-instruct
   ```

2. Install and run the app:

   ```bash
   uv sync --all-extras
   uv run streamlit run app.py --server.address 127.0.0.1
   ```

   Or with pip: `pip install -e ".[dev,statements]"`, then `streamlit run app.py`.

3. Open http://127.0.0.1:8501.

The app has no login, so keep it on `127.0.0.1`. Data is stored in
`data/portfolio.sqlite3`.

## Using the app

### Parse a statement

1. Upload PDF or CSV statements (up to 10 MB and 100 pages each).
2. Pick an **Ollama model** and select **Extract balances**.
3. Check every row against the original document.
4. Select **Edit extracted rows** to fix dates, amounts or descriptions, or to
   add or delete rows. Then **Apply corrections** or **Cancel corrections**.
5. Confirm and save.

Good to know:

- **Text only.** Scanned PDFs need OCR first. CSVs must be UTF-8.
- **Password-protected PDFs.** The app asks for the password during import and
  forgets it afterwards.
- **Chunked processing.** Long statements are read in small chunks (3 PDF pages
  or 50 CSV rows). If any chunk fails, nothing is saved.
- **Self-correction.** The model gets one retry per chunk, plus a small targeted
  repair for a few invalid fields or rows.
- **Stop anytime.** **Stop extraction** cancels the run; finished previews stay
  available for review.
- **Manual direction fixes.** Withdrawals and deposits are kept as the model read
  them. Fix any mistakes yourself in the editor (see
  [#10](https://github.com/sridevs/barelyrich/issues/10)).
- **Live diagnostics.** While the model runs, you see its output and speed. This
  may include financial data, so be careful with screenshots.

### Manual valuation

Use this for assets and debts without statements, such as property, gold or
loans. Enter the total value of your share. Reusing the same name adds a
dated update.

### Overview

Shows net worth and history in INR or SGD, with values carried forward until
you update them. Exchange rates come from [Frankfurter](https://frankfurter.dev/).
Out-of-date values and rates are flagged.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `WT_DATA_DIR` | `data/` | Where the portfolio database is stored |
| `WT_OLLAMA_MODEL` | `qwen3:4b-instruct` | Default model selected in the app |
| `WT_OLLAMA_CONTEXT_TOKENS` | `40960` | Model context window (max 131,072) |
| `WT_OLLAMA_MAX_NEW_TOKENS` | `16384` | Output limit per attempt (max 32,768) |
| `WT_OLLAMA_MAX_TIME_SECONDS` | `900` | Time limit per attempt |

Use only downloaded local models, not cloud-backed Ollama models.

## Privacy and backups

Statements and model inference never leave your machine. Only currency codes and
dates are sent to Frankfurter. The SQLite file is not encrypted, so keep it on
an encrypted disk (for example, FileVault).

Stop the app first, then create an encrypted backup:

```bash
python -m src.backup create data/portfolio.sqlite3 backups/portfolio.enc
python -m src.backup restore backups/portfolio.enc data/portfolio-restored.sqlite3
```

You'll be prompted for a passphrase. Store it safely, and test that you can
restore a backup.

## Development

```bash
uv run pytest -q                                   # full suite with coverage
uv run pytest --no-cov tests/ui tests/integration  # UI and integration only
```

| Package | Responsibility |
| --- | --- |
| `src/models` | Domain models and financial rules |
| `src/readers` | PDF and CSV text extraction |
| `src/agents` | Statement prompts, parsing and validation |
| `src/inference` | Ollama runtime, progress and cancellation |
| `src/service` | Application services connecting the UI to storage |
| `src/repo` | SQLite storage (schema in `src/repo/queries/schema.sql`) |
| `src/providers` | Exchange-rate provider |
| `src/ui` | Streamlit interface |

The database has no migrations. Older databases must be reset.

### Commit messages

Start with the issue number, then a conventional type and a short imperative summary:

```text
[#<issue-number>] <type>: <imperative summary>
```

Example:

```text
[#2] feat: support password-protected PDFs and larger statement inputs
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`. Add a body after a
blank line when the change needs context.
