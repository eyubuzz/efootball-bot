import os
import sys
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_ID   = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")

missing = [k for k, v in {"BOT_TOKEN": BOT_TOKEN, "ADMIN_ID": ADMIN_ID, "CHANNEL_ID": CHANNEL_ID}.items() if not v]
if missing:
    print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
    print("Set them in Railway → your service → Variables tab.")
    sys.exit(1)

ADMIN_ID = int(ADMIN_ID)
