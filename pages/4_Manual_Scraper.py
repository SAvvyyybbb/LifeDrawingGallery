# pages/stage06_manual_scraper.py
import streamlit as st
import discord
import asyncio
import config
from datetime import datetime, timezone
import pandas as pd
from discord_scraper import sha256_bytes, normalize_extension, PhashCache
import aiohttp
from PIL import Image
import imagehash
import io
import os

st.set_page_config(page_title="Manual Scrape Tool", layout="wide")

st.title("🔦 Manual Targeted Scraper")
st.markdown("Use this tool to pull images from a specific channel and time range.")

# ---------------- Load Data from DB for Selection ----------------
conn = config.get_db_connection()
cursor = conn.cursor()

# Get available channels from metadata or config
cursor.execute("SELECT value FROM metadata WHERE key='DISCORD_CHANNELS'")
row = cursor.fetchone()
if row:
    import json
    CHANNELS = {v: int(k) for k, v in json.loads(row[0]).items()}
else:
    CHANNELS = {v: k for k, v in config.CHANNEL_CATEGORIES.items()}

# ---------------- UI Controls ----------------
col1, col2 = st.columns(2)

with col1:
    target_channel_name = st.selectbox("Select Channel from Database", options=list(CHANNELS.keys()))
    manual_channel_id = st.text_input("OR Paste Manual Channel ID (Optional)", help="If you paste an ID here, it will override the selection above.")
    
    if manual_channel_id.strip():
        target_channel_id = int(manual_channel_id.strip())
        display_name = f"Manual ID: {target_channel_id}"
    else:
        target_channel_id = CHANNELS[target_channel_name]
        display_name = target_channel_name

with col2:
    date_range = st.date_input("Select Date Range", value=(datetime(2026, 1, 1), datetime.now()))

st.info(f"Targeting: **{display_name}** from **{date_range[0]}** to **{date_range[1] if len(date_range) > 1 else 'Now'}**")

if st.button("Start Targeted Scrape"):
    if len(date_range) < 2:
        st.error("Please select both a start and end date.")
        st.stop()

    start_dt = datetime.combine(date_range[0], datetime.min.time()).replace(tzinfo=timezone.utc)
    end_dt = datetime.combine(date_range[1], datetime.max.time()).replace(tzinfo=timezone.utc)

    # Internal Scraping Logic (Mini version of discord_scraper.py)
    async def run_manual_scrape():
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        
        status_container = st.empty()
        progress_bar = st.progress(0)
        
        @client.event
        async def on_ready():
            try:
                try:
                    channel = await client.fetch_channel(target_channel_id)
                except discord.NotFound:
                    status_container.error("Could not find channel/thread. Ensure the bot has access.")
                    await client.close()
                    return
                except discord.Forbidden:
                    status_container.error("Forbidden. The bot does not have permission to view this channel/thread.")
                    await client.close()
                    return

                db_conn = config.get_db_connection()
                db_cursor = db_conn.cursor()
                cache = PhashCache(db_cursor)
                
                new_count = 0
                processed_count = 0
                
                status_container.info("Scanning history...")
                
                async with aiohttp.ClientSession() as session:
                    async for msg in channel.history(after=start_dt, before=end_dt, oldest_first=True):
                        processed_count += 1
                        status_container.text(f"Checked {processed_count} messages... Found {new_count} new images.")
                        
                        for att in msg.attachments:
                            if not (att.content_type and att.content_type.startswith("image")): continue
                            
                            async with session.get(att.url) as r:
                                if r.status != 200: continue
                                data = await r.read()
                            
                            img_hash = sha256_bytes(data)
                            db_cursor.execute("SELECT 1 FROM raw_image_data WHERE hash=%s", (img_hash,))
                            if db_cursor.fetchone(): continue
                            
                            image = Image.open(io.BytesIO(data))
                            img_phash = imagehash.phash(image)
                            
                            if cache.is_duplicate(img_phash): continue
                            
                            ext = normalize_extension(os.path.splitext(att.filename)[1] or ".png")
                            local_path = config.RAW_DIR / f"{img_hash}{ext}"
                            local_path.write_bytes(data)
                            
                            storage_key = config.upload_to_supabase(local_path, "raw_images")
                            if storage_key:
                                db_cursor.execute("""
                                    INSERT INTO raw_image_data (
                                        hash, phash, poster_id, poster_name,
                                        message_id, channel_id, original_filename, created_at, 
                                        processing, batched, veto, storage_key_raw, content_category
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s, %s)
                                """, (
                                    img_hash, str(img_phash), msg.author.id, str(msg.author),
                                    msg.id, msg.channel.id, att.filename, datetime.now(timezone.utc),
                                    storage_key, target_channel_name
                                ))
                                db_conn.commit()
                                new_count += 1
                                local_path.unlink()

                status_container.success(f"Done! Scraped **{new_count}** new images from {processed_count} messages.")
                await client.close()
            except Exception as e:
                status_container.error(f"Error: {e}")
                await client.close()

        await client.start(config.TOKEN)

    asyncio.run(run_manual_scrape())

conn.close()
