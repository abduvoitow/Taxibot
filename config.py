import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SECRET_GROUP_ID = int(os.getenv("SECRET_GROUP_ID", 0))

# Gemini API kalitlari (bitta yoki bir nechta vergul bilan: KEY1,KEY2,KEY3)
raw_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
GEMINI_API_KEYS = [k.strip() for k in raw_keys.replace(";", ",").split(",") if k.strip()]
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None
