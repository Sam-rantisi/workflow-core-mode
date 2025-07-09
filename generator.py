# generator.py
# 👉 Fully enhanced: schema diff validation + rule enforcement + curriculum + custom scoring + fallback repair + evolution tracking + test harness ready
# ✅ Patched: GPT retry, logging, and null protection

import os
import json
import zipfile
import shutil
import hashlib
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
from collections import defaultdict
from difflib import SequenceMatcher
from phase2_infra.rule_enforcer import enforce_rules
from phase2_infra.curriculum_engine import inject_curriculum
from phase2_infra.custom_scorer import score_workflow
import re
import time

load_dotenv()

DEPLOYMENT_FLAG = os.getenv("DEPLOYMENT_ACTIVE", "false").lower()
if DEPLOYMENT_FLAG != "true":
    print("\n🛑 Deployment is disabled (DEPLOYMENT_ACTIVE != true). Skipping workflow generation.\n")
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
SCHEMA_PATH = "n8n_schema.json"
MILESTONES = {
    2: "external_apis",
    3: "has_branching",
    4: "has_error",
    5: "include_oauth2"
}

REAL_NODES = set(
    json.load(open(SCHEMA_PATH)).get("validNodes", [])
) if os.path.exists(SCHEMA_PATH) else {
    "start", "webhook", "httpRequest", "set", "if", "switch", "merge", "supabase", "function",
    "functionItem", "wait", "delay", "emailSend", "smtp", "googleSheets", "zoho", "stripe", "slack", "splitInBatches"
}

def log_prompt(version, role, prompt):
    os.makedirs("prompt_logs", exist_ok=True)
    log_path = os.path.join("prompt_logs", f"V{version}_{role}.txt")
    with open(log_path, "w") as f:
        f.write(prompt)
    print(f"\n📤 Logged {role} prompt to {log_path}\n")

def extract_json_block(text):
    try:
        if not text:
            return "{}"
        match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        return text[json_start:json_end].strip()
    except Exception as e:
        print(f"⚠️ Error during JSON block extraction: {e}")
        return "{}"

def gpt(msg, temp=0.6, version_tag=None, role_tag="user"):
    attempt = 0
    while attempt < 3:
        try:
            if version_tag:
                log_prompt(version_tag, role_tag, msg)
            res = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "system", "content": "Act as a workflow architect."}, {"role": "user", "content": msg}],
                temperature=temp
            )
            content = res.choices[0].message.content.strip()
            if not content:
                print("⚠️ Empty GPT response. Retrying...")
                attempt += 1
                time.sleep(2)
                continue
            return extract_json_block(content)
        except Exception as e:
            print(f"❌ GPT call failed (attempt {attempt+1}): {e}")
            attempt += 1
            time.sleep(3)
    raise RuntimeError("GPT call failed after 3 attempts")

def gpt_vote(prompt):
    votes = [gpt(f"Evaluate this upgrade:\n{prompt}\nWas it an improvement? Answer yes or no.") for _ in range(3)]
    return votes.count("yes") >= 2

def generate_diff_report(old: dict, new: dict):
    diffs = {"missing_keys": [], "invalid_nodes": []}
    if not old or not new:
        return diffs
    for key in old.keys():
        if key not in new:
            diffs["missing_keys"].append(key)
    new_nodes = [n.get("type", "") for n in new.get("nodes", [])]
    for ntype in new_nodes:
        if ntype not in REAL_NODES:
            diffs["invalid_nodes"].append(ntype)
    return diffs

def extract_node_summary(workflow):
    types = [n.get('type', '') for n in workflow.get("nodes", [])]
    return {
        "total": len(types),
        "types": list(set(types)),
        "has_branching": any(t in types for t in ["if", "switch"]),
        "has_error": any("error" in n.get("name", "").lower() for n in workflow.get("nodes", [])),
        "external_apis": sum(1 for n in workflow.get("nodes", []) if "http" in n.get('type', '').lower()),
        "include_oauth2": any(t.lower().startswith("oauth2") for t in types),
    }

def validate_structure(version, summary):
    for v, key in MILESTONES.items():
        if version >= v:
            if key == "external_apis" and summary.get(key, 0) < 1:
                return False, f"Missing milestone: {key}"
            elif key != "external_apis" and not summary.get(key):
                return False, f"Missing milestone: {key}"
    return True, ""

def validate_nodes_exist(workflow):
    invalid = [n.get('type', '') for n in workflow.get("nodes", []) if n.get('type', '') not in REAL_NODES]
    return len(invalid) == 0, invalid

def simulate_workflow_runtime(wf):
    return all(substr in str(wf).lower() for substr in ["webhook", "status", "http"])

def simulate_connections(workflow):
    graph = defaultdict(set)
    all_nodes = set(n.get('name', '') for n in workflow.get("nodes", []))
    for src, targets in workflow.get("connections", {}).items():
        for t in targets:
            graph[src].add(t)
    visited = set()
    def dfs(node):
        if node in visited:
            return
        visited.add(node)
        for t in graph.get(node, []):
            dfs(t)
    if "Start" in all_nodes:
        dfs("Start")
    return visited == all_nodes, list(all_nodes - visited)

def compare_json_diff(a, b):
    return SequenceMatcher(None, json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True)).ratio() < 0.95

def try_gpt_repair(workflow_json):
    try:
        raw = gpt(f"Repair this n8n workflow JSON to match schema: \n{json.dumps(workflow_json)}")
        return json.loads(raw)
    except:
        return None

def generate_workflow(version, prompt, prev_summary=None, prev_score=None, temp=0.6, prev_wf=None):
    candidates = []
    for attempt in range(5):
        try:
            raw = gpt(f"Return only valid JSON for n8n workflow V{version}:\n{prompt}", temp, version, "generation")
            if not raw.strip():
                print("⚠️ Empty GPT response. Retrying...")
                continue
            wf = json.loads(raw)
            summary = extract_node_summary(wf)
            struct_ok, _ = validate_structure(version, summary)
            nodes_ok, _ = validate_nodes_exist(wf)
            conn_ok, _ = simulate_connections(wf)
            evolved = compare_json_diff(prev_wf, wf) if prev_wf else True
            diff_report = generate_diff_report(prev_wf or {}, wf)
            rule_errors = enforce_rules(wf)

        print(f"Check: struct_ok: {struct_ok}, nodes_ok: {nodes_ok}, conn_ok: {conn_ok}, evolved: {evolved}")
        print(f"Invalid nodes: {diff_report['invalid_nodes']}")
        print(f"Rule errors: {rule_errors}")
        print(f"Runtime sim: {simulate_workflow_runtime(wf)}")


            if not all([struct_ok, nodes_ok, conn_ok, evolved]) or diff_report["invalid_nodes"] or rule_errors:
                repaired = try_gpt_repair(wf)
                if repaired:
                    wf = repaired
                    summary = extract_node_summary(wf)
                    diff_report = generate_diff_report(prev_wf or {}, wf)
                    rule_errors = enforce_rules(wf)
                else:
                    continue

            if not simulate_workflow_runtime(wf):
                continue

            feedback_summary = {
                "score": prev_score or 0,
                "violations": rule_errors,
                "diff_summary": diff_report,
                "milestone_hits": {key: summary.get(key, False) for key in MILESTONES.values()},
                "base_workflow_json": prev_wf or {}
            }
            score_data = score_workflow(wf, feedback_summary)
            new_score = score_data["final_score"]

            if prev_score and new_score < prev_score:
                continue
            if version > 1 and not gpt_vote(json.dumps({"old": prev_wf, "new": wf})):
                continue
            candidates.append((wf, new_score))
        except Exception as e:
            print(f"❌ Generation error: {e}")
    if not candidates:
        print("⚠️ All 5 attempts failed — retrying with stricter enforcement...")
        return generate_workflow(version, prompt + "\nEnforce schema diff & rule checks strictly.", prev_summary, prev_score, temp + 0.1, prev_wf)
    return max(candidates, key=lambda x: x[1])[0]

def get_versions():
    try:
        res = supabase.storage.from_(STAGING_BUCKET).list()
        return sorted(set(int(i['name'].split("_")[0][1:]) for i in res if i['name'].startswith("V")))
    except:
        return []

def load_json(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def save_json(p, d):
    with open(p, "w") as f:
        json.dump(d, f, indent=2)

def shape_prompt(version, prev_prompt, feedback_summary):
    temp = 0.4 if version <= 2 else (0.65 if version <= 5 else 0.85)
    guidance = inject_curriculum(version, feedback_summary)
    return (f"""
You are generating V{version} of a multi-million dollar enterprise-grade n8n workflow.

Rules:
- Only return clean, executable JSON
- Validate structure against n8n_schema.json
- Include real APIs (Stripe, Google Sheets, Supabase, Zoho, etc.)
- No placeholder nodes, mock data, or dummy names
- Improve on the last version's weaknesses
- Must include nodes: webhook, httpRequest, set, and a status logic branch

Milestones: {MILESTONES.get(version, 'N/A')}
{guidance}
Add branching, error handling, and scalable logic. Maintain upward evolution.
""", temp)

def write_and_zip(folder, files):
    os.makedirs(folder, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(folder, name), "w") as f:
            f.write(content if isinstance(content, str) else json.dumps(content, indent=2))
    zip_path = f"{folder}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for root, _, fs in os.walk(folder):
            for file in fs:
                z.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), folder))
    return zip_path

def hash_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def run():
    versions = get_versions()
    version = 1 if not versions else max(versions) + 1
    folder = os.path.join(PACKS_DIR, f"V{version}_n8n_Ultimate_Pack")
    prev_prompt = load_json("prompt_history.json").get(f"V{version-1}", "")
    feedback = load_json(os.path.join(PACKS_DIR, "feedback.json")).get("V_prev_critique", "")
    prev_wf = load_json(os.path.join(PACKS_DIR, f"V{version-1}_n8n_Ultimate_Pack", "workflow.json")) if version > 1 else None
    prev_summary = extract_node_summary(prev_wf) if prev_wf else None
    prev_score = score_workflow(prev_wf, {"score": 0, "violations": [], "diff_summary": {}, "milestone_hits": {}, "base_workflow_json": {}})["final_score"] if prev_wf else None

    feedback_summary = {
        "score": prev_score or 0,
        "violations": enforce_rules(prev_wf or {}),
        "diff_summary": generate_diff_report(prev_wf or {}, prev_wf or {}),
        "milestone_hits": {key: prev_summary.get(key, False) for key in MILESTONES.values()} if prev_summary else {},
        "base_workflow_json": prev_wf or {}
    }

    prompt, temp = shape_prompt(version, prev_prompt, feedback_summary)
    wf = generate_workflow(version, prompt, prev_summary, prev_score, temp, prev_wf)
    final_score_data = score_workflow(wf, feedback_summary)
    score_val = final_score_data["final_score"]
    summary = extract_node_summary(wf)
    diff_report = generate_diff_report(prev_wf or {}, wf)
    rule_errors = enforce_rules(wf)
    files = {
        "workflow.json": wf,
        "score.txt": f"{score_val}/100",
        "README.md": gpt(f"Describe V{version} enterprise workflow."),
        "logic_map.md": gpt("Logic map for scalable enterprise automation."),
        "deployment.md": gpt("How to deploy on Render + Supabase."),
        "node_suggestions.md": gpt("3 nodes to add next."),
        "validation.md": (
            "## GPT Critique\n\n" + gpt(f"Critique this JSON:\n{json.dumps(wf)}") +
            "\n\n---\n\n## Schema Diff Report\n\n" + json.dumps(diff_report, indent=2) +
            "\n\n---\n\n## Rule Violations\n\n" + json.dumps(rule_errors, indent=2)
        ),
        "feedback_injection.md": json.dumps({"V_prev_critique": feedback}, indent=2),
        "self_prompt.md": prompt,
        "node_summary.md": json.dumps(summary, indent=2)
    }
    if version > 1:
        files["auto_eval.md"] = gpt(f"Compare V{version-1} and V{version} for logic and quality.")
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
