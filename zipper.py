import zipfile, os

def zip_version(version):
    folder = f"{version}_n8n_Ultimate_Pack"
    os.makedirs(folder, exist_ok=True)
    os.rename(f"workflow_{version.lower()}.json", os.path.join(folder, f"workflow_{version.lower()}.json"))
    os.rename("README.md", os.path.join(folder, "README.md"))
    zip_path = f"{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        for f in os.listdir(folder):
            z.write(os.path.join(folder, f), arcname=os.path.join(folder, f))
    return zip_path
