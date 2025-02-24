import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

# Google Sheets Authentication
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("your_credentials.json", scope)
client = gspread.authorize(creds)

# Open the spreadsheet by ID (from your link)
spreadsheet = client.open_by_key("1XEw4Xj7zkMSLfHBDwOuk_tHRR3XlkuwrBvsb5x-ANf8")
sheet = spreadsheet.sheet1  # Use the first sheet

# Fetch the merged cell content (F2:L8)
data = sheet.get("F2:L8")
text_content = "\n".join([cell[0] for cell in data])  # Combine the merged cell's text

# Clean the text for Discord (replace multiple newlines with a single one)
message = f"📢 **Announcement:**\n{text_content.strip()}"

# Discord Webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1343515563422515251/D8JB5FDGtraudJ-xVTMlveBxI2kA_Eh0-QIJwMnaWSsODBgJEpL3YATbo9jpunCUCHKJ"

# Optional: You can specify a thread ID to reply to a specific forum thread
# If you want to start a new thread, remove the 'thread_id' parameter.
thread_id = "123456789012345678"  # Use the thread ID if you want to reply to a specific thread

payload = {
    "content": message,
    "thread_id": thread_id  # Uncomment this line if replying to an existing thread
}

# Send the message to the Forum channel via Webhook
requests.post(DISCORD_WEBHOOK_URL, json=payload)

print("Announcement Sent to Forum Channel!")
    input("\nPress Enter to exit...")