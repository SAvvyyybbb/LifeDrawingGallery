import streamlit as st
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import asyncio
import importlib

import config
import discord_scraper  # renamed from bot.py

# ==============================
# Page title
# ==============================
st.title("Discord Artwork Scraper Control Panel")

# ------------------------------
# Scrape DB
# ------------------------------
SCRAPE_DB_PATH = config.DB_DIR / "scrape_runs.db"
SCRAPE_DB_PATH.parent.mkdir(exist_ok=True, parents=True)

def init_scrape_db():
    conn = sqlite3.connect(SCRAPE_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            scrape_start TEXT,
            scrape_end TEXT,
            first_message_seen TEXT,
            last_message_seen TEXT,
            messages_seen INTEGER DEFAULT 0,
            new_images INTEGER DEFAULT 0,
            duplicate_refreshed INTEGER DEFAULT 0,
            already_processing_skipped INTEGER DEFAULT 0,
            previously_batched_skipped INTEGER DEFAULT 0,
            duplicate_skipped INTEGER DEFAULT 0,
            invalid_images INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_scrape_db()

# ------------------------------
# Show last scrape
# ------------------------------
conn = sqlite3.connect(SCRAPE_DB_PATH)
cur = conn.cursor()
cur.execute("SELECT * FROM scrape_runs ORDER BY run_id DESC LIMIT 1")
row = cur.fetchone()
if row:
    st.subheader("Last Scrape Run")
    st.write({
        "Run ID": row[0],
        "Started At": row[1],
        "Finished At": row[2],
        "Scrape Window": f"{row[3]} → {row[4]}",
        "Messages Seen": row[7],
        "New Images": row[8],
        "Duplicates Refreshed": row[9],
        "Already Processing Skipped": row[10],
        "Previously Batched": row[11],
        "Other Duplicates": row[12],
        "Invalid Images": row[13],
    })
else:
    st.write("No previous runs found.")
conn.close()

# ==============================
# Date selection
# ==============================
st.subheader("Configure Scrape Window")

today = datetime.now(timezone.utc).date()
start_date = st.date_input("Start Date", value=today)
end_date = st.date_input("End Date", value=today)

SCRAPE_START = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
SCRAPE_END   = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

st.write(f"Scrape window set: {SCRAPE_START} → {SCRAPE_END}")

# ==============================
# Discord report toggle
# ==============================
send_report = st.checkbox("Send summary report to Discord?", value=True)

# ==============================
# Counters & preview
# ==============================
status_area = st.empty()
progress_bar = st.progress(0)
counter_area = st.empty()
raw_preview = st.empty()

stats = {
    "messages_seen": 0,
    "new_images": 0,
    "duplicate_refreshed": 0,
    "already_processing_skipped": 0,
    "previously_batched_skipped": 0,
    "duplicate_skipped": 0,
    "invalid_images": 0
}

def update_display():
    counter_area.write(
        f"""
        **Messages seen:** {stats['messages_seen']}
        **New images:** {stats['new_images']}
        **Duplicates refreshed:** {stats['duplicate_refreshed']}
        **Already processing skipped:** {stats['already_processing_skipped']}
        **Previously batched skipped:** {stats['previously_batched_skipped']}
        **Other duplicates:** {stats['duplicate_skipped']}
        **Invalid images:** {stats['invalid_images']}
        """
    )

    files = sorted(config.RAW_DIR.glob("*.[pj][pn]g"), key=lambda x: x.stat().st_mtime, reverse=True)
    if files:
        raw_preview.write([f.name for f in files[:10]])
    else:
        raw_preview.write("No images in RAW_DIR yet")

# ==============================
# Run Scrape Button
# ==============================
if st.button("Run Scrape"):
    st.write("Starting scrape...")

    async def run_scrape():
        # Patch bot to use Streamlit stats, overrides, and report toggle
        await discord_scraper.main_logic(
            stats_dict=stats,
            update_fn=update_display,
            override_start=SCRAPE_START,
            override_end=SCRAPE_END,
            send_report=send_report
        )

    asyncio.run(run_scrape())
    st.success("Scrape completed!")
