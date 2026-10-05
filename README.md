# LinkedIn → Telegram Job Monitor

Monitors LinkedIn's public logged-out job search for:

- Google — Milan, Lombardy, Italy
- Microsoft — Milan, Lombardy, Italy
- SILICON BOX — Italy

It checks jobs posted in the last 24 hours and uses `seen_jobs.json` to prevent duplicate Telegram alerts.

## 1. Install locally

```bash
cd linkedin_telegram_job_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Dry-run LinkedIn

```bash
python monitor.py --dry-run
```

This fetches and prints matching jobs but sends no Telegram messages and does not modify `seen_jobs.json`.

## 3. Configure Telegram locally

```bash
export TELEGRAM_BOT_TOKEN='YOUR_BOT_TOKEN'
export TELEGRAM_CHAT_ID='YOUR_CHAT_ID'
python monitor.py --test-telegram
```

## 4. Create the baseline

Run:

```bash
python monitor.py
```

On the first normal run, all currently visible jobs are written to `seen_jobs.json` but NOT sent to Telegram. Only jobs discovered after that baseline will generate alerts.

## 5. GitHub

Create a GitHub repository and add these files.

Create these repository secrets under:

Settings → Secrets and variables → Actions → New repository secret

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The included workflow runs every 5 minutes and commits `seen_jobs.json` only when it changes.

You can also run it manually from:

Actions → LinkedIn Job Monitor → Run workflow

## Notes

This uses LinkedIn's public logged-out guest job pages, not an official supported LinkedIn API. LinkedIn can change or throttle those endpoints, so the scraper may occasionally require maintenance.
