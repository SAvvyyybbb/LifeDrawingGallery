import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import os
from datetime import datetime
import json

# Load credentials from GitHub Secrets
GOOGLE_CREDENTIALS_JSON = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
SPREADSHEET_ID = "1XEw4Xj7zkMSLfHBDwOuk_tHRR3XlkuwrBvsb5x-ANf8"

# Debug: Starting script
print("🔍 Starting script execution...")

try:
    # Authenticate with Google Sheets
    print("🔑 Authenticating with Google Sheets...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS_JSON, scope)
    client = gspread.authorize(creds)
    print("✅ Authentication successful!")
    
    # Open the spreadsheet and get the sheet
    print("📂 Accessing the spreadsheet...")
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1  
    print("✅ Spreadsheet accessed successfully!")
    
    # Read all data from the sheet
    print("📊 Fetching sheet data...")
    data = sheet.get_all_values()  # Gets all rows as a list of lists
    print(f"✅ Retrieved {len(data)} rows from the sheet.")
    
    # Find the next unchecked prompt
    print("🔍 Searching for the next unchecked prompt...")
    for i, row in enumerate(data[1:], start=2):  # Skip header (assuming row 1 is headers)
        if len(row) < 3:
            print(f"⚠️ Skipping row {i} due to insufficient columns.")
            continue
        
        prompt = row[1]  # Column B (Index 1)
        announced = row[2].strip().lower()  # Column C (Checkbox, Index 2)

        print(f"DEBUG: Row {i}: Prompt: {prompt}, Announced: {announced}")

        # Only check the checkbox status
        if announced != "true":  # If not marked as announced
            if not prompt:
                print(f"⚠️ Skipping row {i} as prompt is empty.")
                continue  # Skip if there's no prompt

            print(f"📢 Found unchecked prompt: {prompt}")

            # Get the current date to include in the announcement (DD Month Year format)
            current_date = datetime.now().strftime("%d %B %Y")  # e.g., "24 February 2025"

            # Format Discord announcement message with more gravitas and date
            message = f"""
<@&1227638634963009586>
🎨 **Hello fellow artists!** 🌟

I'm thrilled to announce this week's Life Drawing prompt as of **{current_date}**: 
 
**"{prompt}"**!

This prompt is an opportunity for you to explore and create something fun to you! The goal is to interpret it in your own way, using whatever medium or technique resonates with you. Let your imagination run wild while maintaining respect and creativity.

This challenge is open to everyone—whether you’re working in VR, traditional media, or something else entirely, your creativity is what counts. Feel free to share as many submissions as you like. The more, the better!

A new prompt will be available every week, but submissions are **always welcome**. It’s never too late to join in and contribute.  
If there’s a prompt from the past that caught your eye, feel free to revisit it and add your own twist. There’s no expiration on inspiration!

Looking forward to seeing your amazing interpretations and creative work! 🎨✨
"""

            # Send the message to Discord
            print("📤 Sending announcement to Discord...")
            response = requests.post(DISCORD_WEBHOOK_URL, json={"content": message})
            
            # Check response status and print appropriate message
            if response.status_code == 204:
                print(f"✅ Announcement for prompt '{prompt}' sent successfully!")
                
                # Mark prompt as announced (tick the checkbox in Column C)
                print("✅ Marking prompt as announced in Google Sheets...")
                sheet.update_cell(i, 3, "TRUE")
                print(f"✅ Prompt '{prompt}' marked as announced.")
            else:
                print(f"❌ Failed to send announcement: {response.status_code} - {response.text}")
            
            break  # Stop after the first unchecked prompt is found and sent
    
    else:
        print("✅ All prompts have already been announced!")

except Exception as e:
    print(f"❌ An error occurred: {e}")
