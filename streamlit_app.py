import streamlit as st
import subprocess
import os
import sys
import time

# 1. Background Bot Spawner
# We only want to start the bot once per Streamlit session/reboot
if "bot_started" not in st.session_state:
    st.session_state.bot_started = True
    
    # Path to your bot script
    bot_script = os.path.join(os.getcwd(), "discord_scraper.py")
    
    # We use the same python executable streamlit is using
    try:
        # We start the bot as a completely separate process
        subprocess.Popen([sys.executable, bot_script], 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE, 
                         start_new_session=True)
        print("[Cloud] Discord Bot process spawned in background.")
    except Exception as e:
        print(f"[Cloud] Failed to spawn bot: {e}")

# 2. Redirect to the actual Home page logic
# Since this is the entry point, we import and run Home.py's content 
# or simply display a message and let the sidebar handle navigation.

st.set_page_config(page_title="Gallery Dashboard", layout="wide")

st.info("🤖 **Beatrice is now awake!** The Discord bot has been started in the background.")

# Import and run the Home logic
import Home
Home.run_home()
