# discord_scraper.py
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from pathlib import Path
import traceback
import asyncio
from PIL import Image
import imagehash
import io
import config

import json

# ---------------- Configuration ----------------
TOKEN = config.TOKEN
RAW_DIR = config.RAW_DIR 
DOWNLOAD_RETRIES = config.DOWNLOAD_RETRIES
BATCH_COMMIT_SIZE = config.BATCH_COMMIT_SIZE

TESTING_MODE = config.TESTING_MODE
CHANNEL_CATEGORIES = config.CHANNEL_CATEGORIES
ACCEPT_EMOJI = config.ACCEPT_EMOJI
DUPLICATE_EMOJI = config.DUPLICATE_EMOJI
VETO_EMOJI = config.VETO_EMOJI
INVALID_EMOJI = config.INVALID_EMOJI
SEARCH_AFTER = config.SEARCH_AFTER.replace(tzinfo=timezone.utc)
SEARCH_BEFORE = None
TEST_MODE_NO_REACT = False # Fallback

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    return ".jpg" if ext == ".jpeg" else ext

def get_last_message_id(cursor, channel_id):
    cursor.execute("SELECT value FROM metadata WHERE key=%s", (f'last_message_id_{channel_id}',))
    row = cursor.fetchone()
    return int(row[0]) if row else None

def set_last_message_id(cursor, conn, channel_id, message_id):
    cursor.execute(
        "INSERT INTO metadata (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (f'last_message_id_{channel_id}', str(message_id))
    )
    conn.commit()

class PhashCache:
    def __init__(self, cursor):
        self.cache = []
        cursor.execute("SELECT hash, phash FROM raw_image_data")
        for row in cursor.fetchall():
            if row[1]:
                self.cache.append((row[0], imagehash.hex_to_hash(row[1])))
        print(f"[Cache] Loaded {len(self.cache)} phashes from Cloud DB.")

    def is_duplicate(self, img_phash):
        for _, existing_phash in self.cache:
            if img_phash - existing_phash == 0:
                return True
        return False

    def add(self, img_phash, img_hash=None):
        self.cache.append((img_hash, img_phash))

# ---------------- Sync DB Helpers (called via asyncio.to_thread) ----------------
def _db_fetch_submissions(user_id: str):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT hash, storage_key_raw, original_filename, veto, content_category
            FROM raw_image_data
            WHERE poster_id = %s
            ORDER BY created_at DESC
            LIMIT 200
        """, (user_id,))
        return list(cursor.fetchall())
    finally:
        conn.close()

def _db_fetch_showcase(user_id: str):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT b.batch_name, b.status, r.original_filename, b.created_at
            FROM raw_image_data r
            JOIN images i ON r.hash = i.hash
            JOIN batches b ON i.batch_id = b.id
            WHERE r.poster_id = %s AND b.status IN ('deployed', 'archived')
            ORDER BY b.created_at DESC
        """, (user_id,))
        return list(cursor.fetchall())
    finally:
        conn.close()

def _db_fetch_gallery_stats():
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT processing, veto, count(*) FROM raw_image_data GROUP BY processing, veto")
        raw_stats = list(cursor.fetchall())
        cursor.execute("SELECT status, count(*) FROM batches GROUP BY status")
        batch_stats = list(cursor.fetchall())
        return raw_stats, batch_stats
    finally:
        conn.close()

def _db_fetch_user_stats(user_id: str):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT processing, veto, count(*) FROM raw_image_data WHERE poster_id = %s GROUP BY processing, veto",
            (user_id,)
        )
        raw_stats = list(cursor.fetchall())
        cursor.execute("""
            SELECT b.status, count(*)
            FROM raw_image_data r
            JOIN images i ON r.hash = i.hash
            JOIN batches b ON i.batch_id = b.id
            WHERE r.poster_id = %s
            GROUP BY b.status
        """, (user_id,))
        batch_stats = list(cursor.fetchall())
        return raw_stats, batch_stats
    finally:
        conn.close()

def _db_toggle_veto(hashes_to_toggle: list, all_items: list):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor()
        updates = {}
        for item in all_items:
            if item['hash'] in hashes_to_toggle:
                new_veto = 0 if item['veto'] else 1
                cursor.execute("UPDATE raw_image_data SET veto = %s WHERE hash = %s", (new_veto, item['hash']))
                updates[item['hash']] = new_veto
        conn.commit()
        return updates
    finally:
        conn.close()

def _db_fetch_reaction_target(message_id: int):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT r.poster_id, r.hash, r.message_id, i.batch_id, b.status as batch_status, b.batch_name
            FROM raw_image_data r
            LEFT JOIN images i ON r.hash = i.hash
            LEFT JOIN batches b ON i.batch_id = b.id
            WHERE r.message_id = %s
        """, (message_id,))
        return cursor.fetchone()
    finally:
        conn.close()

def _db_apply_veto(message_id: int):
    conn = config.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE raw_image_data SET veto = 1 WHERE message_id = %s", (message_id,))
        conn.commit()
    finally:
        conn.close()

# ---------------- Bot Setup ----------------
class GalleryBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Sync slash commands
        await self.tree.sync()
        print(f"[Bot] Tree synced.")

bot = GalleryBot()

# ---------------- Interaction Components ----------------
class SubmissionsView(discord.ui.View):
    def __init__(self, user_id, items):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.all_items = items
        self.current_page = 0
        self.items_per_page = 4
        self.filter_channel = "All"
        
        # Get unique channels
        self.channels = ["All"] + sorted(list(set(i['content_category'] for i in items if i.get('content_category'))))
        
        self.build_ui()

    def get_filtered_items(self):
        if self.filter_channel == "All":
            return self.all_items
        return [i for i in self.all_items if i.get('content_category') == self.filter_channel]

    def build_ui(self):
        self.clear_items()
        filtered = self.get_filtered_items()
        max_pages = max(1, (len(filtered) + self.items_per_page - 1) // self.items_per_page)
        self.current_page = min(self.current_page, max_pages - 1)
        
        page_items = filtered[self.current_page * self.items_per_page : (self.current_page + 1) * self.items_per_page]

        # 1. Channel Filter (Row 0)
        if len(self.channels) > 1:
            options = [discord.SelectOption(label=c, default=(c == self.filter_channel)) for c in self.channels[:25]]
            select_channel = discord.ui.Select(placeholder="Filter by Channel...", options=options, row=0)
            
            async def channel_cb(interaction: discord.Interaction):
                self.filter_channel = select_channel.values[0]
                self.current_page = 0
                self.build_ui()
                await interaction.response.edit_message(embeds=self.get_embeds(), view=self)
            
            select_channel.callback = channel_cb
            self.add_item(select_channel)
            
        # 2. Veto Multi-Select (Row 1)
        if page_items:
            veto_options = []
            for idx, item in enumerate(page_items):
                status = "🔴 Vetoed" if item['veto'] else "🟢 Active"
                name = item['original_filename'] or "Unknown"
                veto_options.append(discord.SelectOption(
                    label=f"{idx+1}. {name[:50]}", 
                    description=f"Status: {status}", 
                    value=item['hash']
                ))
                
            select_veto = discord.ui.Select(
                placeholder="Toggle Veto status for images on this page...", 
                min_values=1, 
                max_values=len(veto_options), 
                options=veto_options, 
                row=1
            )
            
            async def veto_cb(interaction: discord.Interaction):
                selected_hashes = list(select_veto.values)
                updates = await asyncio.to_thread(_db_toggle_veto, selected_hashes, self.all_items)
                for item in self.all_items:
                    if item['hash'] in updates:
                        item['veto'] = updates[item['hash']]
                self.build_ui()
                await interaction.response.edit_message(embeds=self.get_embeds(), view=self)
                
            select_veto.callback = veto_cb
            self.add_item(select_veto)

        # 3. Nav Buttons (Row 2)
        prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.gray, disabled=(self.current_page == 0), row=2)
        async def prev_cb(interaction: discord.Interaction):
            self.current_page -= 1
            self.build_ui()
            await interaction.response.edit_message(embeds=self.get_embeds(), view=self)
        prev_btn.callback = prev_cb
        self.add_item(prev_btn)
        
        page_indicator = discord.ui.Button(label=f"Page {self.current_page + 1} / {max_pages} ({len(filtered)} items)", style=discord.ButtonStyle.blurple, disabled=True, row=2)
        self.add_item(page_indicator)

        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.gray, disabled=(self.current_page == max_pages - 1), row=2)
        async def next_cb(interaction: discord.Interaction):
            self.current_page += 1
            self.build_ui()
            await interaction.response.edit_message(embeds=self.get_embeds(), view=self)
        next_btn.callback = next_cb
        self.add_item(next_btn)

    def get_embeds(self):
        filtered = self.get_filtered_items()
        page_items = filtered[self.current_page * self.items_per_page : (self.current_page + 1) * self.items_per_page]
        
        if not page_items:
            return [discord.Embed(title="No images found", description="Try selecting a different channel filter.", color=discord.Color.red())]
            
        embeds = []
        base_url = config.SUPABASE_URL
        
        for idx, item in enumerate(page_items):
            image_url = f"{base_url}/storage/v1/object/public/raw_images/{item['storage_key_raw']}"
            color = discord.Color.red() if item['veto'] else discord.Color.green()
            category = item.get('content_category') or 'Unknown'
            
            embed = discord.Embed(
                title=f"{idx+1}. {item['original_filename']}",
                description=f"**Channel:** {category}\n**Status:** {'🔴 VETOED' if item['veto'] else '🟢 ACTIVE'}",
                color=color
            )
            embed.set_image(url=image_url)
            embeds.append(embed)
            
        return embeds

@bot.tree.command(name="my_submissions", description="View your submitted artworks, filter by channel, and veto them if needed.")
async def my_submissions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    items = await asyncio.to_thread(_db_fetch_submissions, str(interaction.user.id))
    if not items:
        await interaction.followup.send("You haven't submitted any images yet (or none have been scraped since the cutoff).", ephemeral=True)
        return
    view = SubmissionsView(interaction.user.id, items)
    await interaction.followup.send(embeds=view.get_embeds(), view=view, ephemeral=True)

@bot.tree.command(name="my_showcase", description="See which of your artworks have been showcased in the final gallery UVs.")
async def my_showcase(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    items = await asyncio.to_thread(_db_fetch_showcase, str(interaction.user.id))
    if not items:
        await interaction.followup.send("You don't have any artworks currently or previously showcased in the gallery yet. Keep submitting!", ephemeral=True)
        return
        
    current = [item for item in items if item['status'] == 'deployed']
    archived = [item for item in items if item['status'] == 'archived']
    
    embed = discord.Embed(
        title=f"🎨 {interaction.user.display_name}'s Showcase History",
        description="A tracker of your artworks that made it to the final compiled gallery textures.",
        color=discord.Color.gold()
    )
    
    if current:
        current_text = ""
        for item in current[:10]: # Limit display to avoid embed limits
            current_text += f"• **{item['original_filename']}** -> `UV Map: {item['batch_name']}`\n"
        if len(current) > 10:
            current_text += f"*...and {len(current) - 10} more!*\n"
        embed.add_field(name="🌟 Currently on Display", value=current_text, inline=False)
        
    if archived:
        arch_text = ""
        for item in archived[:10]:
            arch_text += f"• **{item['original_filename']}** -> `UV Map: {item['batch_name']} (Archived)`\n"
        if len(archived) > 10:
            arch_text += f"*...and {len(archived) - 10} more!*\n"
        embed.add_field(name="📚 Past Showcases (Archived)", value=arch_text, inline=False)
        
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="gallery_stats", description="View overall statistics of the Life Drawing Gallery pipeline.")
async def gallery_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    raw_stats, batch_stats = await asyncio.to_thread(_db_fetch_gallery_stats)
    pending_triage = sum(r['count'] for r in raw_stats if r['processing'] == 0 and r['veto'] == 0)
    total_vetoed = sum(r['count'] for r in raw_stats if r['veto'] == 1)
    pending_batching = sum(r['count'] for r in batch_stats if r['status'] in ('pending', 'complete'))
    pending_validation = sum(r['count'] for r in batch_stats if r['status'] == 'stitched')
    pending_deployment = sum(r['count'] for r in batch_stats if r['status'] == 'validated')
    live_uvs = sum(r['count'] for r in batch_stats if r['status'] == 'deployed')
    archived_uvs = sum(r['count'] for r in batch_stats if r['status'] == 'archived')
    
    embed = discord.Embed(title="📊 Gallery Pipeline Statistics", color=discord.Color.blue())
    embed.add_field(name="📥 1. Raw Submissions", value=f"• Pending Triage: **{pending_triage}** images\n• Vetoed/Rejected: **{total_vetoed}** images", inline=False)
    embed.add_field(name="📦 2. Batch Manager", value=f"• Active Batches: **{pending_batching}**", inline=False)
    embed.add_field(name="🧵 3. Stitching & Validation", value=f"• Pending Validation: **{pending_validation}** batches\n• Ready for Deploy: **{pending_deployment}** batches", inline=False)
    embed.add_field(name="🌟 4. Live Gallery", value=f"• Currently Live UVs: **{live_uvs}**\n• Archived/Legacy UVs: **{archived_uvs}**", inline=False)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="my_stats", description="View your personal contribution statistics to the Gallery.")
async def my_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    raw_stats, batch_stats = await asyncio.to_thread(_db_fetch_user_stats, str(interaction.user.id))

    total_submitted = sum(r['count'] for r in raw_stats)
    total_vetoed = sum(r['count'] for r in raw_stats if r['veto'] == 1)
    live_count = sum(r['count'] for r in batch_stats if r['status'] == 'deployed')
    archived_count = sum(r['count'] for r in batch_stats if r['status'] == 'archived')

    embed = discord.Embed(title=f"📈 {interaction.user.display_name}'s Stats", color=discord.Color.green())
    embed.add_field(name="Total Submissions", value=f"**{total_submitted}** images", inline=True)
    embed.add_field(name="Vetoed", value=f"**{total_vetoed}** images", inline=True)
    embed.add_field(name="Currently Live", value=f"**{live_count}** artworks", inline=True)
    embed.add_field(name="Archived/Past", value=f"**{archived_count}** artworks", inline=True)

    await interaction.followup.send(embed=embed)

# ---------------- Reaction Handling ----------------
@bot.event
async def on_raw_reaction_add(payload):
    """Listen for the veto emoji and update the DB, advising the user of its pipeline state."""
    if str(payload.emoji) != VETO_EMOJI: return
    if payload.user_id == bot.user.id: return

    row = await asyncio.to_thread(_db_fetch_reaction_target, payload.message_id)

    if row and payload.user_id == row['poster_id']:
        print(f"[Veto] User {payload.user_id} vetoed image {row['hash']} (Message: {payload.message_id})")

        await asyncio.to_thread(_db_apply_veto, payload.message_id)

        try:
            channel = await bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            try: await message.remove_reaction(ACCEPT_EMOJI, bot.user)
            except: pass
            await message.add_reaction("⛔")
        except Exception as e:
            print(f"[Veto] Could not update reactions: {e}")

        try:
            user = await bot.fetch_user(payload.user_id)
            status = row['batch_status']
            batch_name = row['batch_name']

            if not status:
                await user.send("✅ **Veto Successful:** Your image was removed from the active queue and will not be batched.")
            elif status in ('pending', 'complete'):
                await user.send(f"⚠️ **Veto Flagged:** Your image was already grouped into batch `{batch_name}`, but we've added a giant red warning to it! Savvb will likely remove it before stitching.")
            elif status in ('stitched', 'validated'):
                await user.send(f"🚨 **Late Veto Warning:** Your image is already baked into a finalized UV Map (`{batch_name}`) waiting for deployment! It has been flagged as vetoed, but you may want to message Savvb to manually abort the deployment.")
            elif status in ('deployed', 'archived'):
                await user.send(f"💀 **Critical Late Veto:** Your image is ALREADY LIVE (or archived) on the repository inside UV Map `{batch_name}`. Clicking Veto *does not* automatically un-publish images. You must contact Savvb immediately to have the texture physically recalled and repacked.")

        except discord.Forbidden:
            print(f"[Veto] Cannot DM user {payload.user_id}. DMs are closed.")
        except Exception as e:
            print(f"[Veto] Error DMing user: {e}")

# ---------------- Scraping Logic ----------------
async def perform_scrape(interaction: discord.Interaction = None):
    """Core scraping logic. If interaction is provided, send updates to Discord."""
    conn = config.get_db_connection()
    cursor = conn.cursor()

    print("[Config] Loading settings from database...")
    cursor.execute("SELECT key, value FROM metadata")
    meta_rows = cursor.fetchall()
    meta_dict = {row[0]: row[1] for row in meta_rows}

    # Load all settings as local variables — don't mutate module globals
    channel_categories = CHANNEL_CATEGORIES.copy()
    search_after = SEARCH_AFTER
    testing_mode = TESTING_MODE
    accept_emoji = ACCEPT_EMOJI
    duplicate_emoji = DUPLICATE_EMOJI
    test_mode_no_react = TEST_MODE_NO_REACT

    if 'DISCORD_CHANNELS' in meta_dict:
        try:
            channel_categories = {int(k): v for k, v in json.loads(meta_dict['DISCORD_CHANNELS']).items()}
        except Exception as e:
            print(f"[Warning] Failed to parse DISCORD_CHANNELS from DB: {e}.")

    if 'SEARCH_AFTER' in meta_dict:
        try:
            search_after = datetime.fromisoformat(meta_dict['SEARCH_AFTER'].replace('Z', '+00:00'))
        except: pass

    testing_mode = meta_dict.get('TESTING_MODE', str(TESTING_MODE)).lower() == 'true'
    test_mode_no_react = meta_dict.get('TEST_MODE_NO_REACT', 'false').lower() == 'true'
    accept_emoji = meta_dict.get('ACCEPT_EMOJI', ACCEPT_EMOJI)
    duplicate_emoji = meta_dict.get('DUPLICATE_EMOJI', DUPLICATE_EMOJI)

    msg = f"[Config] Loaded {len(channel_categories)} channels. Testing Mode: {testing_mode}"
    print(msg)
    if interaction: await interaction.followup.send(f"🕵️ **Scraping Started**\n{msg}", ephemeral=True)

    try:
        phash_cache = PhashCache(cursor)
        total_new_images = 0

        async with aiohttp.ClientSession() as session:
            for channel_id, category_name in channel_categories.items():
                try:
                    channel = await bot.fetch_channel(channel_id)
                except discord.NotFound:
                    err_msg = f"[ERROR] Channel/Thread '{category_name}' ({channel_id}) not found. Skipping..."
                    print(err_msg)
                    if interaction: await interaction.followup.send(err_msg, ephemeral=True)
                    continue
                except discord.Forbidden:
                    err_msg = f"[ERROR] Forbidden from accessing '{category_name}' ({channel_id}). Skipping..."
                    print(err_msg)
                    if interaction: await interaction.followup.send(err_msg, ephemeral=True)
                    continue
                except Exception as e:
                    err_msg = f"[ERROR] Unexpected error fetching '{category_name}' ({channel_id}): {e}"
                    print(err_msg)
                    if interaction: await interaction.followup.send(err_msg, ephemeral=True)
                    continue

                print(f"[Scraper] Processing channel '{category_name}' ({channel_id})...")
                last_message_id = get_last_message_id(cursor, channel_id)
                after = discord.Object(id=last_message_id) if last_message_id else search_after

                try:
                    async for msg_obj in channel.history(limit=None, oldest_first=True, after=after, before=SEARCH_BEFORE):
                        message_saved = False
                        message_duplicated = False

                        for att in msg_obj.attachments:
                            if not (
                                att.content_type and att.content_type.startswith("image") and
                                att.filename.lower().endswith((".png", ".jpg", ".jpeg"))
                            ):
                                continue

                            data = None
                            for _ in range(DOWNLOAD_RETRIES):
                                try:
                                    async with session.get(att.url) as r:
                                        if r.status == 200:
                                            data = await r.read()
                                            break
                                except Exception as e:
                                    print(f"Download attempt failed: {e}")
                                    await asyncio.sleep(0.5)
                            if data is None: continue

                            img_hash = sha256_bytes(data)
                            cursor.execute("SELECT 1 FROM raw_image_data WHERE hash=%s OR modified_hash=%s", (img_hash, img_hash))
                            if cursor.fetchone(): continue

                            try:
                                image = Image.open(io.BytesIO(data))
                                img_phash = imagehash.phash(image)
                            except Exception as e:
                                print(f"Failed to process image for phash: {e}")
                                continue

                            if phash_cache.is_duplicate(img_phash):
                                print(f"[Duplicate] Image found for message ID {msg_obj.id}")
                                message_duplicated = True
                                continue

                            ext = normalize_extension(os.path.splitext(att.filename)[1] or ".png")
                            local_file_path = RAW_DIR / f"{img_hash}{ext}"
                            local_file_path.write_bytes(data)

                            storage_key = config.upload_to_supabase(local_file_path, bucket_name="raw_images")

                            if storage_key:
                                cursor.execute("""
                                    INSERT INTO raw_image_data (
                                        hash, phash, poster_id, poster_name,
                                        message_id, channel_id, original_filename, created_at,
                                        processing, batched, veto, modified_hash, storage_key_raw, content_category
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 0, %s, %s, %s)
                                """, (
                                    img_hash, str(img_phash),
                                    msg_obj.author.id, str(msg_obj.author),
                                    msg_obj.id, msg_obj.channel.id, att.filename,
                                    datetime.now(timezone.utc),
                                    None, storage_key, category_name
                                ))
                                phash_cache.add(img_phash, img_hash)
                                message_saved = True
                                total_new_images += 1
                                try: local_file_path.unlink()
                                except: pass
                            else:
                                print(f"Failed to upload to Supabase.")

                        if not testing_mode and not test_mode_no_react:
                            try:
                                if message_saved: await msg_obj.add_reaction(accept_emoji)
                                elif message_duplicated: await msg_obj.add_reaction(duplicate_emoji)
                            except: pass

                        if BATCH_COMMIT_SIZE > 0 and total_new_images % BATCH_COMMIT_SIZE == 0:
                            conn.commit()

                        set_last_message_id(cursor, conn, channel_id, msg_obj.id)
                except Exception as e:
                    print(f"[Warning] Error in channel '{category_name}': {e}")
                    continue

        conn.commit()

        result_msg = f"[Scraper] Done. New images: {total_new_images}."
        print(result_msg)
        if interaction:
            dashboard_url = "https://lifedrawinggallery.streamlit.app/"
            c2 = conn.cursor()
            c2.execute("SELECT value FROM metadata WHERE key = 'DASHBOARD_URL'")
            row = c2.fetchone()
            if row: dashboard_url = row[0]
            await interaction.followup.send(
                f"✅ **Scraping Complete!** Found `{total_new_images}` new images.\n\n"
                f"👉 [Click here to open the Image Triage Dashboard]({dashboard_url})",
                ephemeral=True
            )
    finally:
        conn.close()

# ---------------- Slash Commands ----------------
@bot.tree.command(name="scrape_now", description="Admin only: Manually trigger the scraper to fetch new images from tracked channels.")
@app_commands.default_permissions(administrator=True)
async def scrape_now(interaction: discord.Interaction):
    """Manually trigger the scraper process. Restricted to admins."""
    await interaction.response.defer(ephemeral=True)
    try:
        await perform_scrape(interaction)
    except Exception as e:
        await interaction.followup.send(f"❌ **Scraping Failed:** {e}", ephemeral=True)
        traceback.print_exc()

# ---------------- Main Logic ----------------
async def main_logic():
    try:
        await bot.wait_until_ready()
        
        while not bot.is_closed():
            try:
                # Perform a silent background scrape every hour just in case
                await perform_scrape(None)
            except Exception as e:
                print(f"[Warning] Background scrape failed: {e}")
            
            # Sleep for 1 hour, checking if bot closed every 5 seconds to gracefully exit
            for _ in range(720):
                if bot.is_closed(): break
                await asyncio.sleep(5)
                
    except Exception as e:
        print(f"An unexpected error occurred in main_logic loop: {e}")
        traceback.print_exc()

# ---------------- Entry Point ----------------
@bot.event
async def on_ready():
    print(f"[Bot] Logged in as {bot.user}")
    bot.loop.create_task(main_logic())

def run_bot():
    if not TOKEN:
        print("ERROR: Bot token is empty.")
        return
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Failed to run bot: {e}")

if __name__ == "__main__":
    run_bot()
