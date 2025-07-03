import os
import zipfile
import shutil
import json

PACKS_DIR = "workflow_core/packs"
LEDGER_FILE = "versions.json"
START_VERSION = 23  # anything ≥ 23 will be evaluated

def is_broken(zip_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            for name in z.namelist():
                if name.endswith("README.md"):
                    with z.open(name) as f:
                        content = f.read().decode()
                        if "GPT error" in content:
                            return True
    except Exception as e:
        print(f"⚠️ Error reading {zip_path}: {e}")
        return True
    return False

def delete_zip_and_folder(version):
    folder = os.path.join(PACKS_DIR, f"V{version}_n8n_Ultimate_Pack")
    zip_path = f"{folder}.zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
        print(f"🗑️ Deleted: {zip_path}")
    if os.path.exists(folder):
        shutil.rmtree(folder)
        print(f"🗑️ Deleted: {folder}")

def clean_and_reset():
    for v in range(START_VERSION, 500):  # scan up to V500
        zip_path = os.path.join(PACKS_DIR, f"V{v}_n8n_Ultimate_Pack.zip")
        if os.path.exists(zip_path) and is_broken(zip_path):
            delete_zip_and_folder(v)
        elif not os.path.exists(zip_path):
            break

    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r") as f:
            data = json.load(f)
        data = [entry for entry in data if entry["version"] < START_VERSION]
        with open(LEDGER_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Ledger cleaned. Now resumes from V{START_VERSION}.")

if __name__ == "__main__":
    clean_and_reset()
