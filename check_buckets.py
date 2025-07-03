from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

try:
    buckets = supabase.storage.list_buckets()
    print("✅ Available buckets:", [b['name'] for b in buckets])
except Exception as e:
    print("❌ Error checking buckets:", e)
