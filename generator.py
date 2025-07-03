import os
import uuid
import json
import zipfile
import hashlib
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
from openai import OpenAI
import random
import shutil
import time
import subprocess

load_dotenv()

required_env_vars = {
    "SUPABASE_URL": os.getenv("SUPABASE_URL"),
    "SUPABASE_SERVICE_KEY": os.getenv("SUPABASE_SERVICE_KEY"),
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
}

missing_vars = [k for k, v in required_env_vars.items() if not v]
if missing_vars:
    print(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
    exit(1)

url = required_env_vars["SUPABASE_URL"]
key = required_env_vars["SUPABASE_SERVICE_KEY"]
supabase: Client = create_client(url, key)

client = OpenAI()

PACKS_DIR = "workflow_core/packs"
LOGS_DIR = "logs"
MODE = os.getenv("GENERATOR_MODE", "enterprise")
STAGING_BUCKET = os.getenv("STAGING_BUCKET", "workflowpacks")
PROD_BUCKET = os.getenv("PROD_BUCKET", "workflowpacks")
PRUNE_LIMIT = 10
SCORE_THRESHOLD = 60

VERSION_LEDGER = "versions.json"
FEEDBACK_FILE = "feedback.json"
PROMPT_HISTORY_FILE = "prompt_history.json"
NODE_ANALYSIS_FILE = "node_analysis.json"

def hash_file(file_path):
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def gpt_generate(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"❌ GPT generation failed: {e}")

def llm_score_workflow(workflow):
    prompt = f"Score this n8n workflow from 0-100 for enterprise-readiness: {json.dumps(workflow)}"
    try:
        result = gpt_generate(prompt)
        digits = [int(s) for s in result.split() if s.isdigit() and 0 <= int(s) <= 100]
        return max(digits) if digits else 50
    except:
        return 50

def get_existing_versions():
    try:
        res = supabase.storage.from_(STAGING_BUCKET).list()
        version_nums = []
        for item in res:
            name = item['name']
            if name.startswith("V") and "_n8n_Ultimate_Pack.zip" in name:
                try:
                    v = int(name.split("_")[0][1:])
                    version_nums.append(v)
                except:
                    continue
        return sorted(set(version_nums))
    except Exception as e:
        print(f"⚠️ Failed to fetch versions from Supabase: {e}")
        return []

def summarize_previous_versions():
    summaries = []
    versions = get_existing_versions()
    for v in versions[-3:]:
        path = os.path.join(PACKS_DIR, f"V{v}_n8n_Ultimate_Pack", "workflow.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                summaries.append(f"V{v}: {len(data['nodes'])} nodes, types: {[n['type'] for n in data['nodes']]}")
    return "\n".join(summaries)

def extract_node_patterns(workflow):
    node_types = [n['type'] for n in workflow.get('nodes', [])]
    return {
        "total_nodes": len(node_types),
        "node_distribution": {t: node_types.count(t) for t in set(node_types)}
    }

def shape_prompt(version):
    feedback = load_json(os.path.join(PACKS_DIR, FEEDBACK_FILE))
    prompt_history = load_json(PROMPT_HISTORY_FILE)
    node_patterns = load_json(NODE_ANALYSIS_FILE)
    prev_summary = summarize_previous_versions()
    recent_prompts = "\n---\n".join(prompt_history[-3:] if isinstance(prompt_history, list) else [])
    return f"""
Build the smartest possible enterprise n8n workflow automation pack.
Version: V{version}
Previous Structure:
{prev_summary}
High-Value Feedback:
{json.dumps(feedback, indent=2)}
Prompt Memory:
{recent_prompts}
Node Patterns:
{json.dumps(node_patterns, indent=2)}
Ensure advanced error handling, smart retries, DAG intelligence, multi-API sync, and flow resilience.
"""

def generate_workflow(version):
    prompt = shape_prompt(version)
    try:
        raw_json = gpt_generate(f"Generate full n8n workflow.json based on this prompt:\n{prompt}")
        workflow = json.loads(raw_json)
        prompt_history = load_json(PROMPT_HISTORY_FILE)
        prompt_history.append(prompt)
        save_json(PROMPT_HISTORY_FILE, prompt_history[-10:])
        pattern = extract_node_patterns(workflow)
        save_json(NODE_ANALYSIS_FILE, pattern)
        return workflow
    except:
        print("⚠️ GPT returned non-JSON. Fallback logic activated.")
        return fallback_workflow(version)

def fallback_workflow(version):
    base_nodes = [
        {"name": "Start", "type": "start", "parameters": {}},
        {"name": "Webhook", "type": "webhook", "parameters": {"path": f"v{version}-trigger"}},
        {"name": "HTTP Request", "type": "httpRequest", "parameters": {"url": "https://api.example.com/data"}},
        {"name": "Set", "type": "set", "parameters": {"fields": [{"name": "status", "value": "processed"}]}},
        {"name": "Supabase Insert", "type": "supabase", "parameters": {"table": "events"}}
    ]
    return {
        "name": f"Ultimate_Workflow_V{version}",
        "nodes": base_nodes,
        "connections": {
            base_nodes[i]["name"]: [base_nodes[i+1]["name"]] for i in range(len(base_nodes)-1)
        }
    }

def score_workflow(workflow):
    heuristic = len(workflow["nodes"]) * 10
    if any(n['type'] == "httpRequest" for n in workflow['nodes']): heuristic += 20
    if any(n['type'] == "supabase" for n in workflow['nodes']): heuristic += 15
    if any(n['type'] == "webhook" for n in workflow['nodes']): heuristic += 10
    heuristic = min(heuristic, 100)
    llm_score = llm_score_workflow(workflow)
    return int((heuristic + llm_score) / 2)

def simulate_workflow_logic(workflow):
    required_keys = ["name", "nodes", "connections"]
    for key in required_keys:
        if key not in workflow:
            raise ValueError(f"Missing key: {key}")
    if not workflow["nodes"]:
        raise ValueError("No nodes present")
    return True

def write_and_zip(folder, files):
    os.makedirs(folder, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(folder, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content, indent=2))
    zip_path = f"{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(folder):
            for file in files:
                fp = os.path.join(root, file)
                zipf.write(fp, os.path.relpath(fp, folder))
    return zip_path

def upload(zip_path, bucket):
    file_name = os.path.basename(zip_path)
    existing = supabase.storage.from_(bucket).list()
    if any(obj['name'] == file_name for obj in existing):
        print(f"⚠️ {file_name} already exists in {bucket}, skipping upload.")
        return False
    with open(zip_path, "rb") as f:
        data = f.read()
    res = supabase.storage.from_(bucket).upload(file_name, data, {"content-type": "application/zip"})
    print(f"⬆️ Uploaded {file_name} to {bucket}: {res}")
    return True

def prune():
    packs = get_existing_versions()
    if len(packs) <= PRUNE_LIMIT:
        return
    to_delete = packs[:-PRUNE_LIMIT]
    for v in to_delete:
        folder = f"V{v}_n8n_Ultimate_Pack"
        try:
            shutil.rmtree(os.path.join(PACKS_DIR, folder))
            print(f"🗑️ Pruned local folder {folder}")
        except:
            print(f"⚠️ Failed to prune local folder: {folder}")

def update_ledger(version, score, hashval):
    entry = {
        "version": version,
        "score": score,
        "hash": hashval,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if os.path.exists(VERSION_LEDGER):
        with open(VERSION_LEDGER, "r") as f:
            data = json.load(f)
    else:
        data = []
    data.append(entry)
    with open(VERSION_LEDGER, "w") as f:
        json.dump(data, f, indent=2)

def run():
    versions = get_existing_versions()
    version = max(versions) + 1 if versions else 1
    folder = os.path.join(PACKS_DIR, f"V{version}_n8n_Ultimate_Pack")
    log_folder = os.path.join(LOGS_DIR, f"V{version}")
    os.makedirs(log_folder, exist_ok=True)

    wf1 = generate_workflow(version)
    wf2 = generate_workflow(version)
    simulate_workflow_logic(wf1)
    simulate_workflow_logic(wf2)

    winner = wf1 if score_workflow(wf1) >= score_workflow(wf2) else wf2
    score = score_workflow(winner)
    critique = gpt_generate(f"Critique this n8n workflow: {json.dumps(winner)}")
    feedback_injection = json.dumps(load_json(os.path.join(PACKS_DIR, FEEDBACK_FILE)), indent=2)
    self_prompt = gpt_generate(f"Given this critique, what should V{version+1}'s prompt be? {critique}")

    files = {
        "workflow.json": winner,
        "score.txt": f"{score}/100",
        "README.md": gpt_generate(f"Describe V{version} of an enterprise n8n automation workflow pack."),
        "logic_map.md": gpt_generate("Generate a logic map for a complex enterprise n8n automation pack."),
        "deployment.md": gpt_generate("Instructions for deploying an n8n automation pack on Render + Supabase."),
        "node_suggestions.md": gpt_generate(f"Suggest 3 advanced nodes for V{version} with logic + API."),
        "validation.md": critique,
        "feedback_injection.md": feedback_injection,
        "self_prompt.md": self_prompt
    }
    if version > 1:
        files["auto_eval.md"] = gpt_generate(f"Compare V{version-1} to V{version}. Key improvements?")

    zip_path = write_and_zip(folder, files)
    if not upload(zip_path, STAGING_BUCKET):
        print(f"❌ Skipping update. Version V{version} already exists.")
        return

    update_ledger(version, score, hash_file(zip_path))
    if STAGING_BUCKET != PROD_BUCKET:
        upload(zip_path, PROD_BUCKET)
    prune()
    print(f"✅ V{version} complete. Logs, packs, and ledger updated.")

if __name__ == "__main__":
    run()
