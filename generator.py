# generator_refactored.py
# Ultra-intelligent generator for $100M-grade n8n workflows
# Now with deploy-block switch

import os
import json
import zipfile
import shutil
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

load_dotenv()

# 🛑 HARD STOP IF DEPLOYMENT OFF
if os.getenv("DEPLOYMENT_ACTIVE", "true").lower() != "true":
    print("🚫 Deployment paused. Set DEPLOYMENT_ACTIVE=true to resume.")
    exit()

REQUIRED_VARS = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "OPENAI_API_KEY"]
for var in REQUIRED_VARS:
    if not os.getenv(var):
        raise EnvironmentError(f"Missing required ENV: {var}")

supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
client = OpenAI()

PACKS_DIR = "workflow_core/packs"
STAGING_BUCKET = os.getenv("STAGING_BUCKET", "workflowpacks")
PROD_BUCKET = os.getenv("PROD_BUCKET", "workflowpacks")
VERSION_LEDGER = "versions.json"
PRUNE_LIMIT = 10
SCORE_THRESHOLD = 60

def gpt(msg, temp=0.6):
    res = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": msg}],
        temperature=temp
    )
    return res.choices[0].message.content.strip()

def load_json(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def save_json(p, d):
    with open(p, "w") as f:
        json.dump(d, f, indent=2)

def get_versions():
    try:
        res = supabase.storage.from_(STAGING_BUCKET).list()
        return sorted(set(int(i['name'].split("_")[0][1:]) for i in res if i['name'].startswith("V")))
    except:
        return []

def shape_prompt(version, prev_prompt, feedback):
    return f"""
Build the most advanced, fault-tolerant, enterprise-scale n8n workflow for automation V{version}.
Incorporate feedback from V{version-1}:
{feedback}
Evolve logic, introduce new node types, add retries, fallbacks, API diversity.
Avoid regressions. Maintain forward momentum.
Previous prompt:
{prev_prompt}
"""

def extract_node_summary(workflow):
    types = [n['type'] for n in workflow.get("nodes", [])]
    return {
        "total": len(types),
        "types": list(set(types)),
        "has_branching": any(t in types for t in ["if", "switch"]),
        "has_error": any("error" in n.get("name", "").lower() for n in workflow.get("nodes", [])),
        "external_apis": sum(1 for n in workflow.get("nodes", []) if "http" in n['type'].lower())
    }

def is_structurally_identical(summary1, summary2):
    return summary1 == summary2

def generate_workflow(version, prompt, prev_summary=None):
    for attempt in range(3):
        try:
            raw = gpt(f"Generate n8n workflow.json for V{version} with:\n{prompt}")
            wf = json.loads(raw)
            new_summary = extract_node_summary(wf)
            if prev_summary and is_structurally_identical(new_summary, prev_summary):
                print("❌ Evolution failed — retrying...")
                continue
            return wf
        except:
            print("⚠️ Fallback triggered.")
            return fallback_workflow(version)
    raise RuntimeError("🛑 Failed to evolve workflow after 3 attempts.")

def fallback_workflow(version):
    nodes = [
        {"name": "Start", "type": "start", "parameters": {}},
        {"name": "Webhook", "type": "webhook", "parameters": {"path": f"v{version}-trigger"}},
        {"name": "HTTP Request", "type": "httpRequest", "parameters": {"url": "https://api.example.com"}},
        {"name": "Set", "type": "set", "parameters": {"fields": [{"name": "status", "value": "done"}]}},
        {"name": "Supabase Insert", "type": "supabase", "parameters": {"table": "log"}}
    ]
    return {
        "name": f"Ultimate_V{version}",
        "nodes": nodes,
        "connections": {nodes[i]['name']: [nodes[i+1]['name']] for i in range(len(nodes)-1)}
    }

def score(workflow):
    summary = extract_node_summary(workflow)
    s = summary['total'] * 8
    if summary['has_branching']: s += 10
    if summary['has_error']: s += 10
    if summary['external_apis'] >= 2: s += 10
    try:
        llm = gpt(f"Score this n8n workflow 0–100 for enterprise readiness:\n{json.dumps(workflow)}")
        digits = [int(s) for s in llm.split() if s.isdigit() and 0 <= int(s) <= 100]
        return int((s + (max(digits) if digits else 50)) / 2)
    except:
        return s

def hash_file(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

def write_and_zip(folder, files):
    os.makedirs(folder, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(folder, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content, indent=2))
    zip_path = f"{folder}.zip"
    with zipfile.ZipFile(zip_path, 'w') as z:
        for root, _, fs in os.walk(folder):
            for file in fs:
                z.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), folder))
    return zip_path

def run():
    versions = get_versions()
    version = 1 if not versions else max(versions) + 1
    folder = os.path.join(PACKS_DIR, f"V{version}_n8n_Ultimate_Pack")

    prev_prompt = load_json("prompt_history.json").get(f"V{version-1}", "")
    feedback = load_json(os.path.join(PACKS_DIR, "feedback.json")).get("V_prev_critique", "")
    prompt = shape_prompt(version, prev_prompt, feedback)

    prev_workflow = load_json(os.path.join(PACKS_DIR, f"V{version-1}_n8n_Ultimate_Pack", "workflow.json")) if version > 1 else None
    prev_summary = extract_node_summary(prev_workflow) if prev_workflow else None

    wf = generate_workflow(version, prompt, prev_summary)
    score_val = score(wf)
    summary = extract_node_summary(wf)

    files = {
        "workflow.json": wf,
        "score.txt": f"{score_val}/100",
        "README.md": gpt(f"Describe V{version} enterprise workflow."),
        "logic_map.md": gpt("Logic map for a scalable n8n pack."),
        "deployment.md": gpt("How to deploy on Render + Supabase."),
        "node_suggestions.md": gpt("3 smart nodes to add next version."),
        "validation.md": gpt(f"Critique:\n{json.dumps(wf)}"),
        "feedback_injection.md": json.dumps({"V_prev_critique": feedback}, indent=2),
        "self_prompt.md": prompt,
        "node_summary.md": json.dumps(summary, indent=2)
    }
    if version > 1:
        files["auto_eval.md"] = gpt(f"Compare V{version-1} and V{version} for logic, resilience, node growth.")

    zip_path = write_and_zip(folder, files)
    supabase.storage.from_(STAGING_BUCKET).upload(os.path.basename(zip_path), open(zip_path, "rb"), {"content-type": "application/zip"})
    if STAGING_BUCKET != PROD_BUCKET:
        supabase.storage.from_(PROD_BUCKET).upload(os.path.basename(zip_path), open(zip_path, "rb"), {"content-type": "application/zip"})

    history = load_json("prompt_history.json")
    history[f"V{version}"] = prompt
    save_json("prompt_history.json", history)

    ledger = load_json(VERSION_LEDGER)
    ledger.append({"version": version, "score": score_val, "hash": hash_file(zip_path), "time": datetime.now(timezone.utc).isoformat()})
    save_json(VERSION_LEDGER, ledger)

    print(f"✅ V{version} complete with score {score_val}.")

if __name__ == "__main__":
    run()
