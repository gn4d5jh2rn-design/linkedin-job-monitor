#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"

SEEN_FILE = Path("seen_jobs.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/141.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}

SEARCHES = [
    {
        "name": "Google",
        "keywords": "Google",
        "location": "Milan, Lombardy, Italy",
        "accepted_company_names": {"google"},
    },
    {
        "name": "Microsoft",
        "keywords": "Microsoft",
        "location": "Milan, Lombardy, Italy",
        "accepted_company_names": {"microsoft"},
    },
    {
        "name": "SILICON BOX",
        "keywords": "Silicon Box",
        "location": "Italy",
        "accepted_company_names": {"silicon box"},
    },
]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalized_company(text: str) -> str:
    return normalize(text).lower().replace("®", "").replace("™", "")


def request_with_retries(session, url, *, params=None, timeout=25, attempts=3):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 200:
                return response
            last_error = RuntimeError(
                f"HTTP {response.status_code} from {response.url}"
            )
        except requests.RequestException as exc:
            last_error = exc

        if attempt < attempts:
            time.sleep(2 * attempt)

    raise RuntimeError(f"Request failed after {attempts} attempts: {last_error}")


def extract_job_id(card, url: str) -> str | None:
    urn = card.get("data-entity-urn") or ""
    match = re.search(r"jobPosting:(\d+)", urn)
    if match:
        return match.group(1)

    match = re.search(r"[-/](\d{7,})(?:[/?]|$)", url)
    if match:
        return match.group(1)

    return None


def parse_cards(html: str, search_cfg: dict) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for card in soup.select("div.base-card"):
        title_el = card.select_one(".base-search-card__title")
        company_el = card.select_one(".base-search-card__subtitle")
        location_el = card.select_one(".job-search-card__location")
        link_el = card.select_one("a.base-card__full-link")
        time_el = card.select_one("time")

        if not title_el or not company_el or not link_el:
            continue

        company_raw = normalize(company_el.get_text(" ", strip=True))
        company_norm = normalized_company(company_raw)

        # Crucial safeguard:
        # LinkedIn may show "similar jobs" from unrelated employers.
        if company_norm not in search_cfg["accepted_company_names"]:
            continue

        href = normalize(link_el.get("href") or "")
        if not href:
            continue

        url = urljoin("https://www.linkedin.com", href)
        url = url.split("?")[0]

        job_id = extract_job_id(card, url)
        if not job_id:
            continue

        posted = ""
        if time_el:
            posted = normalize(
                time_el.get("datetime")
                or time_el.get_text(" ", strip=True)
            )

        jobs.append(
            {
                "id": job_id,
                "company": search_cfg["name"],
                "company_raw": company_raw,
                "title": normalize(title_el.get_text(" ", strip=True)),
                "location": normalize(
                    location_el.get_text(" ", strip=True)
                    if location_el else ""
                ),
                "posted": posted,
                "url": url,
            }
        )

    unique = {}
    for job in jobs:
        unique[job["id"]] = job

    return list(unique.values())


def fetch_jobs(session, search_cfg: dict, max_pages: int = 2) -> list[dict]:
    all_jobs = {}

    for page in range(max_pages):
        start = page * 10

        params = {
            "keywords": search_cfg["keywords"],
            "location": search_cfg["location"],
            "f_TPR": "r604800",  # 7 days
            "sortBy": "DD",      # newest first
            "start": start,
        }

        response = request_with_retries(
            session,
            LINKEDIN_SEARCH_URL,
            params=params,
        )

        parsed = parse_cards(response.text, search_cfg)

        for job in parsed:
            all_jobs[job["id"]] = job

        print(
            f"  page start={start}: "
            f"{len(parsed)} exact employer match(es)"
        )

        # Do not stop just because one page has no exact employer matches:
        # LinkedIn can intermix unrelated/similar jobs.
        if len(response.text) < 100:
            break

        time.sleep(0.6)

    return list(all_jobs.values())


def load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {"initialized": False, "jobs": {}}

    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        data.setdefault("initialized", False)
        data.setdefault("jobs", {})
        return data
    except (json.JSONDecodeError, ValueError):
        return {"initialized": False, "jobs": {}}


def save_seen(data: dict):
    jobs = data.get("jobs", {})

    if len(jobs) > 3000:
        keys = list(jobs.keys())[-3000:]
        data["jobs"] = {key: jobs[key] for key in keys}

    SEEN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def send_telegram(message: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID."
        )

    response = requests.post(
        TELEGRAM_URL.format(token=token),
        data={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=25,
    )
    response.raise_for_status()


def telegram_message(job: dict) -> str:
    posted_line = f"\n🕒 {job['posted']}" if job.get("posted") else ""
    location_line = f"\n📍 {job['location']}" if job.get("location") else ""

    return (
        "🚨 NEW LINKEDIN JOB\n\n"
        f"🏢 {job['company']}\n"
        f"💼 {job['title']}"
        f"{location_line}"
        f"{posted_line}\n\n"
        f"🔗 {job['url']}"
    )


def run(dry_run=False):
    session = requests.Session()
    session.headers.update(HEADERS)

    seen = load_seen()
    found_jobs = []
    errors = []

    for cfg in SEARCHES:
        print(f"\n=== {cfg['name']} ===")
        try:
            jobs = fetch_jobs(session, cfg)
            found_jobs.extend(jobs)

            print(
                f"{cfg['name']}: found {len(jobs)} exact matching "
                f"job(s) in the last 7 days for {cfg['location']}."
            )

            for job in sorted(
                jobs,
                key=lambda x: (x.get("posted", ""), x["id"]),
                reverse=True,
            ):
                print(
                    f"  - [{job['id']}] "
                    f"{job['title']} | "
                    f"{job['location']} | "
                    f"{job['posted']}"
                )

        except Exception as exc:
            errors.append(f"{cfg['name']}: {exc}")
            print(
                f"ERROR - {cfg['name']}: {exc}",
                file=sys.stderr
            )

    if dry_run:
        print(
            "\nDry run: no Telegram messages sent "
            "and seen_jobs.json not changed."
        )
        if errors:
            sys.exit(2)
        return

    if not seen.get("initialized"):
        for job in found_jobs:
            seen["jobs"][job["id"]] = job

        seen["initialized"] = True
        save_seen(seen)

        print(
            f"\nInitial baseline created with "
            f"{len(found_jobs)} job(s). "
            "No existing jobs were sent to Telegram."
        )

        if errors:
            sys.exit(2)
        return

    new_jobs = [
        job
        for job in found_jobs
        if job["id"] not in seen["jobs"]
    ]

    sent = 0

    for job in new_jobs:
        try:
            send_telegram(telegram_message(job))
            seen["jobs"][job["id"]] = job
            save_seen(seen)
            sent += 1

            print(
                f"Telegram alert sent: "
                f"{job['company']} - {job['title']}"
            )

        except Exception as exc:
            errors.append(
                f"Telegram {job['id']}: {exc}"
            )
            print(
                f"ERROR sending Telegram for "
                f"{job['id']}: {exc}",
                file=sys.stderr
            )

    for job in found_jobs:
        seen["jobs"].setdefault(job["id"], job)

    save_seen(seen)

    print(
        f"\nNew jobs: {len(new_jobs)} | "
        f"Telegram alerts sent: {sent}"
    )

    if errors:
        print("\nCompleted with errors:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(2)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Monitor LinkedIn guest jobs and send "
            "new exact-employer postings to Telegram."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Fetch and print jobs without Telegram "
            "or changing seen_jobs.json."
        ),
    )

    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send one Telegram test message and exit.",
    )

    args = parser.parse_args()

    if args.test_telegram:
        send_telegram(
            "✅ LinkedIn job monitor test successful.\n\n"
            "Telegram notifications are configured correctly."
        )
        print("Telegram test sent successfully.")
        return

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
