# Quickstart

## 1. Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`
- Telegram Bot token stored as `TELEGRAM_TOKEN` in `.env`
- ERPNext credentials exported as `ERP_BASE_URL`, `ERP_API_KEY`, `ERP_API_SECRET`
- OpenAI API key (`OPENAI_API_KEY`) for the LangGraph LLM + embeddings

## 2. Environment Setup

```bash
python3 -m venv lc-academy-env
source lc-academy-env/bin/activate
pip install -r requirements.txt
cp .env.example .env  # create if not present
```

Populate `.env`:

```bash
TELEGRAM_TOKEN=123456:ABCDEF
TELEGRAM_WEBHOOK_SECRET=longrandomstring
ERP_BASE_URL=https://erp.example.com
ERP_API_KEY=your-key
ERP_API_SECRET=your-secret
OPENAI_API_KEY=sk-...
DEFAULT_COMPANY=Cuenta HQ
DEFAULT_CURRENCY=USD
```

## 3. Run Tests First

```bash
pytest tests/unit
pytest tests/bdd
pytest tests/integration
```

Inline Gherkin lives inside each `tests/bdd/*_steps.py` module; pytest-bdd materializes feature files automatically during collection.

CI will gate on the same commands.

## 4. Start the Bot Locally

```bash
python -m src.expense_bot.app --mode polling
```

This command:
- Loads environment variables
- Starts the LangGraph worker with SQLite checkpoint storage under `var/checkpoints/expense_bot.sqlite`
- Runs the Telegram bot in long-polling mode for development

## 5. Optional: Webhook Mode

```bash
python -m src.expense_bot.app --mode webhook --listen 0.0.0.0 --port 8443 \
  --webhook-url https://bot.example.com/telegram/webhook
```

Configure your reverse proxy to add the `X-Telegram-Bot-Api-Secret-Token` header matching `TELEGRAM_WEBHOOK_SECRET`.

## 6. Verifying ERPNext Integration

1. Send a sample message in Telegram.
2. Confirm the bot presents a summary card.
3. Approve the expense.
4. Check ERPNext → Accounting → Journal Entry for the new record with a remark referencing the Telegram message.

If ERPNext is offline, watch the retry queue with:

```bash
sqlite3 var/checkpoints/expense_bot.sqlite 'SELECT * FROM retry_jobs;'
```

## 7. Updating Documentation

- Log each development session in `change_log.md`.
- After major changes, re-run this quickstart to confirm the steps remain accurate.
