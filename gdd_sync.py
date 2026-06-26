#!/usr/bin/env python3
"""
gdd_sync.py
Fetches daily GDD data from CoAgMet (CSU) station oth01
and writes it to Smartsheet. Runs once daily via GitHub Actions.
"""

import os
import csv
import requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

SHEET_ID = 3210442634645380

COAGMET_URL = (
    "https://coagmet.colostate.edu/data/gdd/oth01.csv"
    "?from=2026-01-01"
    "&to=now"
    "&fields=daily"
)

# Column IDs — leave Primary, Column4, Barley GDD, Column6 alone
COL_DATE = 2086282501771140
COL_GDD  = 6589882129141636

SMARTSHEET_API = "https://api.smartsheet.com/2.0"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_token():
    token = os.environ.get("SMARTSHEET_TOKEN")
    if not token:
        raise EnvironmentError("SMARTSHEET_TOKEN environment variable not set")
    return token


def ss_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def convert_date(date_str):
    """Convert MM/DD/YYYY to YYYY-MM-DD for Smartsheet DATE column."""
    date_str = date_str.strip().strip('"')
    try:
        return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


# ── Step 1: Fetch data ────────────────────────────────────────────────────────

def fetch_data():
    print("Fetching GDD data from CoAgMet...")
    resp = requests.get(COAGMET_URL, timeout=30)
    resp.raise_for_status()

    rows = []
    reader = csv.reader(resp.text.splitlines())
    for row in reader:
        if not row or len(row) < 3:
            continue
        # col 0 = station (ignore), col 1 = date, col 2 = GDD value
        date = convert_date(row[1])
        if not date:
            continue
        raw_val = row[2].strip()
        # -999 is CoAgMet's missing data sentinel — write as blank
        try:
            gdd = float(raw_val)
            gdd_value = None if gdd == -999 else gdd
        except ValueError:
            gdd_value = None
        rows.append({"date": date, "gdd": gdd_value})

    print(f"  Parsed {len(rows)} rows ({sum(1 for r in rows if r['gdd'] is not None)} with data, {sum(1 for r in rows if r['gdd'] is None)} missing)")
    return rows


# ── Step 2: Clear existing rows ───────────────────────────────────────────────

def get_existing_row_ids(token):
    url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}?include=rowIds"
    resp = requests.get(url, headers=ss_headers(token), timeout=60)
    resp.raise_for_status()
    return [r["id"] for r in resp.json().get("rows", [])]


def delete_rows(token, row_ids):
    if not row_ids:
        print("  No existing rows to delete")
        return
    chunk_size = 450
    total = 0
    for i in range(0, len(row_ids), chunk_size):
        chunk = row_ids[i:i + chunk_size]
        ids_param = ",".join(str(rid) for rid in chunk)
        url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows?ids={ids_param}"
        resp = requests.delete(url, headers=ss_headers(token), timeout=60)
        resp.raise_for_status()
        total += len(chunk)
    print(f"  Deleted {total} existing rows")


# ── Step 3: Insert new rows ───────────────────────────────────────────────────

def build_rows(data):
    rows = []
    for d in data:
        cells = [{"columnId": COL_DATE, "value": d["date"]}]
        if d["gdd"] is not None:
            cells.append({"columnId": COL_GDD, "value": d["gdd"]})
        rows.append({"cells": cells})
    return rows


def insert_rows(token, rows):
    chunk_size = 400
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        url = f"{SMARTSHEET_API}/sheets/{SHEET_ID}/rows"
        resp = requests.post(url, headers=ss_headers(token), json=chunk, timeout=60)
        resp.raise_for_status()
        total += len(resp.json().get("result", []))
    print(f"  Inserted {total} rows")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = get_token()

    data = fetch_data()
    if not data:
        raise ValueError("No data parsed — aborting to avoid wiping sheet")

    print("Clearing existing rows...")
    row_ids = get_existing_row_ids(token)
    delete_rows(token, row_ids)

    print("Inserting new rows...")
    rows = build_rows(data)
    insert_rows(token, rows)

    print("Done ✓")


if __name__ == "__main__":
    main()
