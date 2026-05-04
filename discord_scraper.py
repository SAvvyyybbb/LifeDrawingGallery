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
                selected_hashes = select_veto.values
                conn = config.get_db_connection()
                cursor = conn.cursor()
                for item in self.all_items:
                    if item['hash'] in selected_hashes:
                        new_veto = 0 if item['veto'] else 1
                        item['veto'] = new_veto
                        cursor.execute("UPDATE raw_image_data SET veto = %s WHERE hash = %s", (new_veto, item['hash']))
                conn.commit()
                conn.close()
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
    """Fetch user submissions and show a paginated view with multiple images."""
    await interaction.response.defer(ephemeral=True)
    
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Increased limit to 200 to give them a healthy backlog to filter through
    cursor.execute("""
        SELECT hash, storage_key_raw, original_filename, veto, content_category 
        FROM raw_image_data 
        WHERE poster_id = %s 
        ORDER BY created_at DESC 
        LIMIT 200
    """, (interaction.user.id,))
    
    items = cursor.fetchall()
    conn.close()
    
    if not items:
        await interaction.followup.send("You haven't submitted any images yet (or none have been scraped since the cutoff).", ephemeral=True)
        return
        
    view = SubmissionsView(interaction.user.id, items)
    await interaction.followup.send(embeds=view.get_embeds(), view=view, ephemeral=True)

@bot.tree.command(name="my_showcase", description="See which of your artworks have been showcased in the final gallery UVs.")
async def my_showcase(interaction: discord.Interaction):
    """Fetch user's images that are in deployed or archived batches."""
    await interaction.response.defer(ephemeral=True)
    
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT b.batch_name, b.status, r.original_filename, b.created_at
        FROM raw_image_data r
        JOIN images i ON r.hash = i.hash
        JOIN batches b ON i.batch_id = b.id
        WHERE r.poster_id = %s AND b.status IN ('deployed', 'archived')
        ORDER BY b.created_at DESC
    """, (interaction.user.id,))
    
    items = cursor.fetchall()
    conn.close()
    
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

# ---------------- Reaction Handling ----------------
@bot.event
async def on_raw_reaction_add(payload):
    """Listen for the veto emoji and update the DB, advising the user of its pipeline state."""
    if str(payload.emoji) != VETO_EMOJI: return
    if payload.user_id == bot.user.id: return

    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check pipeline state
    cursor.execute("""
        SELECT r.poster_id, r.hash, r.message_id, i.batch_id, b.status as batch_status, b.batch_name
        FROM raw_image_data r
        LEFT JOIN images i ON r.hash = i.hash
        LEFT JOIN batches b ON i.batch_id = b.id
        WHERE r.message_id = %s
    """, (payload.message_id,))
    
    row = cursor.fetchone()
    
    if row and payload.user_id == row['poster_id']:
        print(f"[Veto] User {payload.user_id} vetoed image {row['hash']} (Message: {payload.message_id})")
        
        # 1. Update Database
        cursor.execute("UPDATE raw_image_data SET veto = 1 WHERE message_id = %s", (payload.message_id,))
        conn.commit()
        
        # 2. Update Reactions visually on Discord
        try:
            channel = await bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            try: await message.remove_reaction(ACCEPT_EMOJI, bot.user)
            except: pass
            await message.add_reaction("⛔")
        except Exception as e: 
            print(f"[Veto] Could not update reactions: {e}")
            
        # 3. Determine Pipeline State & DM User
        try:
            user = await bot.fetch_user(payload.user_id)
            status = row['batch_status']
            batch_name = row['batch_name']
            
            if not status: # Not in a batch yet (Raw, Image Triage, or just unbatched)
                await user.send("✅ **Veto Successful:** Your image was removed from the active queue and will not be batched.")
            
            elif status in ('pending', 'complete'): # In Batch Manager
                await user.send(f"⚠️ **Veto Flagged:** Your image was already grouped into batch `{batch_name}`, but we've added a giant red warning to it! Savvb will likely remove it before stitching.")
                
            elif status in ('stitched', 'validated'): # Already baked into a UV Map waiting for deploy
                await user.send(f"🚨 **Late Veto Warning:** Your image is already baked into a finalized UV Map (`{batch_name}`) waiting for deployment! It has been flagged as vetoed, but you may want to message Savvb to manually abort the deployment.")
                
            elif status in ('deployed', 'archived'): # Out in the wild
                await user.send(f"💀 **Critical Late Veto:** Your image is ALREADY LIVE (or archived) on the repository inside UV Map `{batch_name}`. Clicking Veto *does not* automatically un-publish images. You must contact Savvb immediately to have the texture physically recalled and repacked.")
        
        except discord.Forbidden:
            print(f"[Veto] Cannot DM user {payload.user_id}. DMs are closed.")
        except Exception as e:
            print(f"[Veto] Error DMing user: {e}")

    conn.close()

# ---------------- Main Logic ----------------
async def main_logic():
    try:
        await bot.wait_until_ready()
        
        conn = config.get_db_connection()
        cursor = conn.cursor()
        
        print("[Config] Loading settings from database...")
        cursor.execute("SELECT key, value FROM metadata")
        meta_rows = cursor.fetchall()
        meta_dict = {row[0]: row[1] for row in meta_rows}
        
        global CHANNEL_CATEGORIES, SEARCH_AFTER, TESTING_MODE, ACCEPT_EMOJI, DUPLICATE_EMOJI, VETO_EMOJI, TEST_MODE_NO_REACT
        
        if 'DISCORD_CHANNELS' in meta_dict:
            try:
                CHANNEL_CATEGORIES = {int(k): v for k, v in json.loads(meta_dict['DISCORD_CHANNELS']).items()}
            except Exception as e:
                print(f"[Warning] Failed to parse DISCORD_CHANNELS from DB: {e}.")
                
        if 'SEARCH_AFTER' in meta_dict:
            try:
                SEARCH_AFTER = datetime.fromisoformat(meta_dict['SEARCH_AFTER'].replace('Z', '+00:00'))
            except: pass
            
        TESTING_MODE = meta_dict.get('TESTING_MODE', 'true').lower() == 'true'
        TEST_MODE_NO_REACT = meta_dict.get('TEST_MODE_NO_REACT', 'false').lower() == 'true'
        ACCEPT_EMOJI = meta_dict.get('ACCEPT_EMOJI', ACCEPT_EMOJI)
        DUPLICATE_EMOJI = meta_dict.get('DUPLICATE_EMOJI', DUPLICATE_EMOJI)
        VETO_EMOJI = meta_dict.get('VETO_EMOJI', VETO_EMOJI)
        
        print(f"[Config] Loaded {len(CHANNEL_CATEGORIES)} channels. Testing Mode: {TESTING_MODE}")

        phash_cache = PhashCache(cursor)
        total_new_images = 0
        
        async with aiohttp.ClientSession() as session:
            for channel_id, category_name in CHANNEL_CATEGORIES.items():
                try:
                    channel = await bot.fetch_channel(channel_id)
                except discord.NotFound:
                    print(f"[ERROR] Channel/Thread '{category_name}' ({channel_id}) not found. Skipping...")
                    continue
                except discord.Forbidden:
                    print(f"[ERROR] Forbidden from accessing '{category_name}' ({channel_id}). Skipping...")
                    continue
                except Exception as e:
                    print(f"[ERROR] Unexpected error fetching '{category_name}' ({channel_id}): {e}")
                    continue
                
                print(f"[Scraper] Processing channel '{category_name}' ({channel_id})...")
                last_message_id = get_last_message_id(cursor, channel_id)
                after = discord.Object(id=last_message_id) if last_message_id else SEARCH_AFTER
                
                try:
                    async for msg in channel.history(limit=None, oldest_first=True, after=after, before=SEARCH_BEFORE):
                        message_saved = False
                        message_duplicated = False
                        
                        for att in msg.attachments:
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
                                print(f"[Duplicate] Image found for message ID {msg.id}")
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
                                    msg.author.id, str(msg.author),
                                    msg.id, msg.channel.id, att.filename,
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

                        if not TESTING_MODE and not TEST_MODE_NO_REACT:
                            try:
                                if message_saved: await msg.add_reaction(ACCEPT_EMOJI)
                                elif message_duplicated: await msg.add_reaction(DUPLICATE_EMOJI)
                            except: pass
                        
                        if BATCH_COMMIT_SIZE > 0 and total_new_images % BATCH_COMMIT_SIZE == 0:
                            conn.commit()

                        set_last_message_id(cursor, conn, channel_id, msg.id)
                except Exception as e:
                    print(f"[Warning] Error in channel '{category_name}': {e}")
                    continue

        conn.commit()
        conn.close()
        print(f"[Scraper] Done. New images: {total_new_images}.")
        while True: await asyncio.sleep(3600)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
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
