"""
WattCoin Agent Tasks API - Task Routing Marketplace
GET  /api/v1/tasks                    - List all agent tasks (GitHub + external)
POST /api/v1/tasks                    - Create external task (requires WATT payment)
GET  /api/v1/tasks/<id>               - Get single task
POST /api/v1/tasks/<id>/submit        - Submit task result
GET  /api/v1/tasks/<id>/submissions   - List submissions (admin)
POST /api/v1/tasks/<id>/approve       - Manual approve (admin)
POST /api/v1/tasks/<id>/reject        - Manual reject (admin)

v2.4.0 - External task posting with on-chain payment verification
"""

import os
import re
import json
import uuid
import time
import requests
import base58
from flask import Blueprint, jsonify, request
from datetime import datetime
from functools import wraps

tasks_bp = Blueprint('tasks', __name__)

# =============================================================================
# CONFIG
# =============================================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "WattCoin-Org/wattcoin"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/issues"

GROK_API_KEY = os.getenv("GROK_API_KEY", "")
GROK_API_URL = "https://api.x.ai/v1/chat/completions"

BOUNTY_WALLET = "7vvNkG3JF3JpxLEavqZSkc5T3n9hHR98Uw23fbWdXVSF"
BOUNTY_WALLET_PRIVATE_KEY = os.getenv("BOUNTY_WALLET_PRIVATE_KEY", "")
WATT_MINT = "Gpmbh4PoQnL1kNgpMYDED3iv4fczcr7d3qNBLf8rpump"
SOLANA_RPC = "https://solana.publicnode.com"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SUBMISSIONS_FILE = "/app/data/task_submissions.json"
EXTERNAL_TASKS_FILE = "/app/data/external_tasks.json"
AUTO_APPROVE_CONFIDENCE = 0.8  # Auto-approve if Grok confidence >= this

# External task config
TREASURY_WALLET = os.getenv('TREASURY_WALLET', 'Atu5phbGGGFogbKhi259czz887dSdTfXwJxwbuE5aF5q')
MIN_TASK_REWARD = 500  # Minimum WATT to post a task
MAX_TASK_REWARD = 1000000  # Maximum WATT per task

# Cache
_tasks_cache = {"data": None, "expires": 0}
CACHE_TTL = 300  # 5 minutes

# =============================================================================
# STORAGE
# =============================================================================

def load_submissions():
    """Load submissions from JSON file."""
    try:
        with open(SUBMISSIONS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"submissions": []}

def save_submissions(data):
    """Save submissions to JSON file."""
    try:
        os.makedirs(os.path.dirname(SUBMISSIONS_FILE), exist_ok=True)
        with open(SUBMISSIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving submissions: {e}")
        return False

def generate_submission_id():
    """Generate unique submission ID."""
    return f"sub_{uuid.uuid4().hex[:12]}"

def generate_task_id():
    """Generate unique external task ID (starts with 'ext_')."""
    return f"ext_{uuid.uuid4().hex[:8]}"

# =============================================================================
# EXTERNAL TASKS STORAGE
# =============================================================================

def load_external_tasks():
    """Load external tasks from JSON file."""
    try:
        with open(EXTERNAL_TASKS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tasks": []}

def save_external_tasks(data):
    """Save external tasks to JSON file."""
    try:
        os.makedirs(os.path.dirname(EXTERNAL_TASKS_FILE), exist_ok=True)
        with open(EXTERNAL_TASKS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving external tasks: {e}")
        return False

# =============================================================================
# TX VERIFICATION
# =============================================================================

def verify_watt_payment(tx_signature: str, expected_amount: int, from_wallet: str = None) -> dict:
    """
    Verify WATT transfer to treasury wallet.
    Returns: {"valid": bool, "amount": int, "error": str}
    """
    try:
        resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [tx_signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
        }, timeout=15)
        
        data = resp.json()
        if "error" in data or not data.get("result"):
            return {"valid": False, "amount": 0, "error": "Transaction not found"}
        
        tx = data["result"]
        
        # Check age (must be within last 1 hour for task posting)
        block_time = tx.get("blockTime", 0)
        if time.time() - block_time > 3600:
            return {"valid": False, "amount": 0, "error": "Transaction too old (>1 hour)"}
        
        # Check pre/post token balances for WATT transfer to treasury
        meta = tx.get("meta", {})
        pre_balances = meta.get("preTokenBalances", [])
        post_balances = meta.get("postTokenBalances", [])
        
        treasury_pre = 0
        treasury_post = 0
        sender_found = False
        
        for bal in pre_balances:
            if bal.get("mint") == WATT_MINT:
                owner = bal.get("owner", "")
                if owner == TREASURY_WALLET:
                    treasury_pre = int(bal.get("uiTokenAmount", {}).get("amount", 0))
                elif from_wallet and owner == from_wallet:
                    sender_found = True
        
        for bal in post_balances:
            if bal.get("mint") == WATT_MINT:
                owner = bal.get("owner", "")
                if owner == TREASURY_WALLET:
                    treasury_post = int(bal.get("uiTokenAmount", {}).get("amount", 0))
        
        amount_received = (treasury_post - treasury_pre) / 1_000_000  # 6 decimals
        
        if amount_received < expected_amount:
            return {"valid": False, "amount": amount_received, "error": f"Insufficient payment: {amount_received} < {expected_amount} WATT"}
        
        return {"valid": True, "amount": amount_received, "error": None}
        
    except Exception as e:
        return {"valid": False, "amount": 0, "error": str(e)}

# =============================================================================
# AUTH
# =============================================================================

def require_admin(f):
    """Require admin authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if auth != f"Bearer {ADMIN_PASSWORD}":
            return jsonify({"success": False, "error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# =============================================================================
# HELPERS
# =============================================================================

def parse_task_amount(title):
    """Extract WATT amount from title like [AGENT TASK: 1,000 WATT]"""
    match = re.search(r'\[AGENT\s*TASK:\s*([\d,]+)\s*WATT\]', title, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def get_task_type(body):
    """Determine if task is recurring or one-time based on body content."""
    if not body:
        return "one-time"
    body_lower = body.lower()
    if any(word in body_lower for word in ['daily', 'weekly', 'monthly', 'recurring', 'every day', 'every week']):
        return "recurring"
    return "one-time"

def get_frequency(body):
    """Extract frequency from body for recurring tasks."""
    if not body:
        return None
    body_lower = body.lower()
    if 'daily' in body_lower or 'every day' in body_lower:
        return "daily"
    if 'weekly' in body_lower or 'every week' in body_lower:
        return "weekly"
    if 'monthly' in body_lower or 'every month' in body_lower:
        return "monthly"
    return None

def clean_title(title):
    """Remove [AGENT TASK: X WATT] prefix from title."""
    return re.sub(r'\[AGENT\s*TASK:\s*[\d,]+\s*WATT\]\s*', '', title, flags=re.IGNORECASE).strip()

def extract_section(body, header):
    """Extract content under a markdown header."""
    if not body:
        return None
    pattern = rf'#+\s*{header}\s*\n(.*?)(?=\n#+\s|\Z)'
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

# =============================================================================
# FETCH TASKS
# =============================================================================

def fetch_tasks():
    """Fetch agent tasks from GitHub Issues + external tasks."""
    # Check cache
    if _tasks_cache["data"] and time.time() < _tasks_cache["expires"]:
        return _tasks_cache["data"]
    
    tasks = []
    
    # 1. Fetch GitHub Issues with agent-task label
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    try:
        resp = requests.get(
            GITHUB_API,
            params={"labels": "agent-task", "state": "open", "per_page": 50},
            headers=headers,
            timeout=15
        )
        
        if resp.status_code == 200:
            issues = resp.json()
            
            for issue in issues:
                amount = parse_task_amount(issue["title"])
                if amount == 0:
                    continue
                
                body = issue.get("body", "") or ""
                task_type = get_task_type(body)
                
                task = {
                    "id": issue["number"],
                    "source": "github",
                    "title": clean_title(issue["title"]),
                    "amount": amount,
                    "type": task_type,
                    "frequency": get_frequency(body) if task_type == "recurring" else None,
                    "description": extract_section(body, "Description") or body[:500] if body else None,
                    "requirements": extract_section(body, "Requirements"),
                    "submission_format": extract_section(body, "Submission") or extract_section(body, "How to Submit"),
                    "url": issue["html_url"],
                    "created_at": issue["created_at"],
                    "labels": [l["name"] for l in issue.get("labels", []) if l["name"] != "agent-task"],
                    "body": body,  # Keep full body for verification
                    "poster": "WattCoin-Org"
                }
                tasks.append(task)
        
    except Exception as e:
        print(f"Error fetching GitHub tasks: {e}")
    
    # 2. Load external tasks
    try:
        external_data = load_external_tasks()
        for ext_task in external_data.get("tasks", []):
            if ext_task.get("status") == "open":
                tasks.append(ext_task)
    except Exception as e:
        print(f"Error loading external tasks: {e}")
    
    # Sort by amount descending
    tasks.sort(key=lambda x: x["amount"], reverse=True)
    
    # Update cache
    _tasks_cache["data"] = tasks
    _tasks_cache["expires"] = time.time() + CACHE_TTL
    
    return tasks

def get_task_by_id(task_id):
    """Get task by ID (handles both GitHub numeric IDs and external string IDs)."""
    tasks = fetch_tasks()
    
    # Handle both int and string IDs
    for task in tasks:
        if str(task["id"]) == str(task_id):
            return task
    
    # Also check external tasks directly (bypassing cache) for external IDs
    if isinstance(task_id, str) and task_id.startswith("ext_"):
        external_data = load_external_tasks()
        for ext_task in external_data.get("tasks", []):
            if ext_task["id"] == task_id:
                return ext_task
    
    return None

# =============================================================================
# GROK VERIFICATION
# =============================================================================

def verify_with_grok(task, submission_result):
    """
    Use Grok to verify if submission meets task requirements.
    Returns: {"pass": bool, "reason": str, "confidence": float}
    """
    if not GROK_API_KEY:
        return {"pass": False, "reason": "Grok API not configured", "confidence": 0}
    
    prompt = f"""You are verifying an AI agent's task submission.

TASK: {task['title']}

REQUIREMENTS:
{task.get('requirements') or task.get('description') or 'Complete the task as described.'}

SUBMISSION:
{json.dumps(submission_result, indent=2)}

Evaluate if this submission meets the task requirements.
Reply with ONLY valid JSON (no markdown):
{{"pass": true/false, "reason": "brief explanation", "confidence": 0.0-1.0}}

Be strict but fair. Confidence should reflect how certain you are about your evaluation."""

    try:
        resp = requests.post(
            GROK_API_URL,
            headers={
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "grok-4-1-fast-reasoning",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1
            },
            timeout=30
        )
        
        if resp.status_code != 200:
            return {"pass": False, "reason": f"Grok API error: {resp.status_code}", "confidence": 0}
        
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Parse JSON response
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content)
        return {
            "pass": bool(result.get("pass", False)),
            "reason": str(result.get("reason", "No reason provided")),
            "confidence": float(result.get("confidence", 0))
        }
        
    except json.JSONDecodeError as e:
        return {"pass": False, "reason": f"Failed to parse Grok response: {e}", "confidence": 0}
    except Exception as e:
        return {"pass": False, "reason": f"Grok verification error: {e}", "confidence": 0}

# =============================================================================
# SOLANA PAYOUT
# =============================================================================

def send_watt_payout(to_wallet, amount):
    """
    Send WATT tokens from bounty wallet to recipient.
    Returns: (success, tx_signature or error_message)
    
    Currently queues for manual payout via dashboard.
    Auto-payout requires BOUNTY_WALLET_PRIVATE_KEY and additional testing.
    """
    if not BOUNTY_WALLET_PRIVATE_KEY:
        # Queue for manual payout - this is the expected flow for now
        return False, "Queued for manual payout via dashboard"
    
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey
        from solders.instruction import Instruction, AccountMeta
        from solders.transaction import Transaction
        from solders.message import Message
        from solders.hash import Hash
        import struct
        
        # Token-2022 program ID (WATT uses Token-2022)
        TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
        ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        
        # Load wallet from private key
        key_bytes = base58.b58decode(BOUNTY_WALLET_PRIVATE_KEY)
        wallet = Keypair.from_bytes(key_bytes)
        
        mint = Pubkey.from_string(WATT_MINT)
        from_pubkey = wallet.pubkey()
        to_pubkey = Pubkey.from_string(to_wallet)
        
        # Get ATAs via RPC (more reliable than calculating)
        def get_ata_for_owner(owner_str):
            resp = requests.post(SOLANA_RPC, json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [owner_str, {"mint": WATT_MINT}, {"encoding": "jsonParsed"}]
            }, timeout=15)
            data = resp.json()
            accounts = data.get("result", {}).get("value", [])
            if accounts:
                return Pubkey.from_string(accounts[0]["pubkey"])
            return None
        
        from_ata = get_ata_for_owner(str(from_pubkey))
        to_ata = get_ata_for_owner(to_wallet)
        
        if not from_ata:
            return False, "Bounty wallet has no WATT token account"
        if not to_ata:
            return False, f"Recipient {to_wallet[:8]}... has no WATT token account. They need to receive WATT first."
        
        # Build transfer instruction (opcode 3 for SPL token transfer)
        amount_raw = amount * (10 ** 6)  # 6 decimals
        instruction_data = struct.pack('<BQ', 3, amount_raw)
        
        # Account metas for transfer: [source, dest, owner]
        accounts = [
            AccountMeta(from_ata, is_signer=False, is_writable=True),
            AccountMeta(to_ata, is_signer=False, is_writable=True),
            AccountMeta(from_pubkey, is_signer=True, is_writable=False),
        ]
        
        transfer_ix = Instruction(TOKEN_2022_PROGRAM_ID, instruction_data, accounts)
        
        # Get recent blockhash
        rpc_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "finalized"}]
        }, timeout=15)
        blockhash_data = rpc_resp.json()
        blockhash = Hash.from_string(blockhash_data["result"]["value"]["blockhash"])
        
        # Build and sign transaction
        msg = Message.new_with_blockhash([transfer_ix], from_pubkey, blockhash)
        tx = Transaction.new_unsigned(msg)
        tx.sign([wallet], blockhash)
        
        # Serialize and send
        tx_bytes = bytes(tx)
        tx_base64 = base58.b58encode(tx_bytes).decode('utf-8')
        
        send_resp = requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [tx_base64, {"encoding": "base58", "skipPreflight": False}]
        }, timeout=30)
        
        send_result = send_resp.json()
        
        if "result" in send_result:
            return True, send_result["result"]
        elif "error" in send_result:
            return False, f"RPC error: {send_result['error'].get('message', str(send_result['error']))}"
        else:
            return False, "Unknown RPC response"
            
    except ImportError as e:
        return False, f"Solana libraries not installed: {e}"
    except Exception as e:
        return False, f"Payout error: {e}"

# =============================================================================
# GITHUB COMMENT
# =============================================================================

def post_github_comment(issue_number, comment):
    """Post a comment on a GitHub issue."""
    if not GITHUB_TOKEN:
        return False
    
    try:
        resp = requests.post(
            f"{GITHUB_API}/{issue_number}/comments",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={"body": comment},
            timeout=15
        )
        return resp.status_code == 201
    except:
        return False

def close_github_issue(issue_number):
    """Close a GitHub issue."""
    if not GITHUB_TOKEN:
        return False
    
    try:
        resp = requests.patch(
            f"{GITHUB_API}/{issue_number}",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            },
            json={"state": "closed"},
            timeout=15
        )
        return resp.status_code == 200
    except:
        return False

# =============================================================================
# ENDPOINTS - PUBLIC
# =============================================================================

@tasks_bp.route('/api/v1/tasks', methods=['GET'])
def list_tasks():
    """List all agent tasks (GitHub + external)."""
    tasks = fetch_tasks()
    
    # Optional filters
    task_type = request.args.get('type')  # recurring, one-time
    source = request.args.get('source')  # github, external
    min_amount = request.args.get('min_amount', type=int)
    
    if task_type:
        tasks = [t for t in tasks if t["type"] == task_type]
    
    if source:
        tasks = [t for t in tasks if t.get("source") == source]
    
    if min_amount:
        tasks = [t for t in tasks if t["amount"] >= min_amount]
    
    # Remove body from public response
    tasks_public = [{k: v for k, v in t.items() if k != 'body'} for t in tasks]
    
    total_watt = sum(t["amount"] for t in tasks)
    github_count = len([t for t in tasks if t.get("source") == "github"])
    external_count = len([t for t in tasks if t.get("source") == "external"])
    
    return jsonify({
        "success": True,
        "count": len(tasks),
        "github_tasks": github_count,
        "external_tasks": external_count,
        "total_watt": total_watt,
        "tasks": tasks_public,
        "post_endpoint": "/api/v1/tasks",
        "submit_endpoint": "/api/v1/tasks/{id}/submit",
        "docs": f"https://github.com/{GITHUB_REPO}/blob/main/CONTRIBUTING.md"
    })

@tasks_bp.route('/api/v1/tasks', methods=['POST'])
def create_task():
    """
    Create an external task. Requires WATT payment to treasury.
    
    Request:
    {
        "title": "Task title",
        "description": "What needs to be done",
        "reward": 5000,  // WATT amount
        "tx_signature": "abc123...",  // Proof of payment
        "poster_wallet": "AgentWallet...",
        "type": "one-time",  // or "recurring"
        "frequency": "daily",  // optional, for recurring
        "deadline": "2026-02-10"  // optional ISO date
    }
    
    Response:
    {
        "success": true,
        "task_id": "ext_abc123",
        "status": "open"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "invalid_json"}), 400
    
    # Validate required fields
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    reward = data.get("reward")
    tx_signature = data.get("tx_signature", "").strip()
    poster_wallet = data.get("poster_wallet", "").strip()
    
    if not title:
        return jsonify({"success": False, "error": "missing_title"}), 400
    if len(title) > 200:
        return jsonify({"success": False, "error": "title_too_long", "message": "Max 200 characters"}), 400
    if not description:
        return jsonify({"success": False, "error": "missing_description"}), 400
    if len(description) > 5000:
        return jsonify({"success": False, "error": "description_too_long", "message": "Max 5000 characters"}), 400
    if not reward or not isinstance(reward, (int, float)):
        return jsonify({"success": False, "error": "missing_reward"}), 400
    if reward < MIN_TASK_REWARD:
        return jsonify({"success": False, "error": "reward_too_low", "message": f"Minimum reward is {MIN_TASK_REWARD} WATT"}), 400
    if reward > MAX_TASK_REWARD:
        return jsonify({"success": False, "error": "reward_too_high", "message": f"Maximum reward is {MAX_TASK_REWARD} WATT"}), 400
    if not tx_signature:
        return jsonify({"success": False, "error": "missing_tx_signature", "message": "Payment tx signature required"}), 400
    if not poster_wallet or len(poster_wallet) < 32:
        return jsonify({"success": False, "error": "missing_poster_wallet"}), 400
    
    reward = int(reward)
    
    # Check if tx_signature already used
    external_data = load_external_tasks()
    for existing in external_data.get("tasks", []):
        if existing.get("tx_signature") == tx_signature:
            return jsonify({"success": False, "error": "tx_already_used", "message": "This transaction was already used"}), 400
    
    # Verify payment on-chain
    payment_check = verify_watt_payment(tx_signature, reward, poster_wallet)
    if not payment_check["valid"]:
        return jsonify({
            "success": False, 
            "error": "payment_verification_failed",
            "message": payment_check["error"]
        }), 400
    
    # Create task
    task_id = generate_task_id()
    task_type = data.get("type", "one-time")
    if task_type not in ["one-time", "recurring"]:
        task_type = "one-time"
    
    new_task = {
        "id": task_id,
        "source": "external",
        "title": title,
        "description": description,
        "amount": reward,
        "type": task_type,
        "frequency": data.get("frequency") if task_type == "recurring" else None,
        "deadline": data.get("deadline"),
        "poster": poster_wallet,
        "tx_signature": tx_signature,
        "status": "open",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "url": None,  # No GitHub URL for external tasks
        "labels": ["external"],
        "requirements": description,  # Use description as requirements
        "submission_format": "Submit proof of completion via /api/v1/tasks/{id}/submit",
        "body": description,
        "submissions_count": 0,
        "completed_by": None,
        "completed_at": None
    }
    
    external_data["tasks"].append(new_task)
    save_external_tasks(external_data)
    
    # Clear cache
    _tasks_cache["data"] = None
    
    return jsonify({
        "success": True,
        "task_id": task_id,
        "status": "open",
        "reward": reward,
        "message": f"Task created! {reward} WATT will be paid to first valid submission.",
        "submit_endpoint": f"/api/v1/tasks/{task_id}/submit"
    })

@tasks_bp.route('/api/v1/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get single task by ID (supports both GitHub numeric and external string IDs)."""
    # Try to convert to int for GitHub tasks
    try:
        task_id_parsed = int(task_id)
    except ValueError:
        task_id_parsed = task_id  # Keep as string for external tasks
    
    task = get_task_by_id(task_id_parsed)
    
    if not task:
        return jsonify({
            "success": False,
            "error": "task_not_found",
            "message": f"Task {task_id} not found or not open"
        }), 404
    
    # Remove body from public response
    task_public = {k: v for k, v in task.items() if k != 'body'}
    
    return jsonify({
        "success": True,
        "task": task_public
    })

@tasks_bp.route('/api/v1/tasks/<task_id>/submit', methods=['POST'])
def submit_task(task_id):
    """
    Submit task result for verification and payout.
    
    Request:
        {"result": {...}, "wallet": "AgentWalletAddress"}
    
    Response:
        {"success": true, "submission_id": "sub_xxx", "status": "pending_review|approved|paid"}
    """
    # Parse task_id (could be int for GitHub or string for external)
    try:
        task_id_parsed = int(task_id)
    except ValueError:
        task_id_parsed = task_id  # Keep as string for external tasks
    
    # Validate request
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "invalid_json"}), 400
    
    result = data.get("result")
    wallet = data.get("wallet")
    
    if not result:
        return jsonify({"success": False, "error": "missing_result", "message": "result field is required"}), 400
    if not wallet:
        return jsonify({"success": False, "error": "missing_wallet", "message": "wallet field is required"}), 400
    
    # Validate wallet format (basic check)
    if len(wallet) < 32 or len(wallet) > 50:
        return jsonify({"success": False, "error": "invalid_wallet", "message": "Invalid Solana wallet address"}), 400
    
    # Get task
    task = get_task_by_id(task_id_parsed)
    if not task:
        return jsonify({"success": False, "error": "task_not_found", "message": f"Task {task_id} not found or not open"}), 404
    
    # Check if external task is already completed
    if task.get("source") == "external" and task.get("status") != "open":
        return jsonify({"success": False, "error": "task_closed", "message": "This task is no longer open"}), 400
    
    # Create submission
    submission_id = generate_submission_id()
    submission = {
        "id": submission_id,
        "task_id": task_id_parsed,
        "task_source": task.get("source", "github"),
        "task_title": task["title"],
        "amount": task["amount"],
        "wallet": wallet,
        "result": result,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "status": "pending_review",
        "grok_review": None,
        "tx_signature": None,
        "paid_at": None,
        "reviewed_at": None
    }
    
    # Verify with Grok
    grok_review = verify_with_grok(task, result)
    submission["grok_review"] = grok_review
    submission["reviewed_at"] = datetime.utcnow().isoformat() + "Z"
    
    # Determine status based on Grok review
    if grok_review["pass"] and grok_review["confidence"] >= AUTO_APPROVE_CONFIDENCE:
        submission["status"] = "approved"
        
        # Auto-payout
        success, tx_or_error = send_watt_payout(wallet, task["amount"])
        
        if success:
            submission["status"] = "paid"
            submission["tx_signature"] = tx_or_error
            submission["paid_at"] = datetime.utcnow().isoformat() + "Z"
            
            # Handle based on task source
            if task.get("source") == "github":
                # Post GitHub comment
                comment = f"""## ✅ Task Completed - Auto-Verified

**Submission ID:** `{submission_id}`
**Agent Wallet:** `{wallet}`
**Payout:** {task["amount"]:,} WATT
**TX:** [{tx_or_error[:16]}...](https://solscan.io/tx/{tx_or_error})

---
*Verified by Grok AI (confidence: {grok_review["confidence"]:.0%})*
"""
                post_github_comment(task_id_parsed, comment)
                
                # Close issue if one-time task
                if task["type"] == "one-time":
                    close_github_issue(task_id_parsed)
            else:
                # External task - update status in JSON
                external_data = load_external_tasks()
                for ext_task in external_data.get("tasks", []):
                    if ext_task["id"] == task_id_parsed:
                        if task["type"] == "one-time":
                            ext_task["status"] = "completed"
                        ext_task["completed_by"] = wallet
                        ext_task["completed_at"] = datetime.utcnow().isoformat() + "Z"
                        ext_task["submissions_count"] = ext_task.get("submissions_count", 0) + 1
                        break
                save_external_tasks(external_data)
        else:
            # Check if it's queued for manual payout (expected) vs actual failure
            if "manual payout" in tx_or_error.lower():
                submission["status"] = "approved"  # Verified, awaiting manual payout
                submission["payout_note"] = "Awaiting manual payout via dashboard"
            else:
                submission["status"] = "payout_failed"
                submission["payout_error"] = tx_or_error
    
    elif grok_review["pass"]:
        # Pass but low confidence - queue for manual review
        submission["status"] = "pending_review"
    
    else:
        # Failed verification
        submission["status"] = "rejected"
    
    # Save submission
    submissions_data = load_submissions()
    submissions_data["submissions"].append(submission)
    save_submissions(submissions_data)
    
    # Clear task cache so updated info is fetched
    _tasks_cache["data"] = None
    
    return jsonify({
        "success": True,
        "submission_id": submission_id,
        "task_id": task_id_parsed,
        "status": submission["status"],
        "grok_review": grok_review,
        "tx_signature": submission.get("tx_signature"),
        "message": {
            "paid": f"Task completed! {task['amount']:,} WATT sent to {wallet[:8]}...",
            "approved": f"Task verified by Grok! {task['amount']:,} WATT payout pending admin approval.",
            "pending_review": "Submitted for manual review (Grok confidence below threshold).",
            "rejected": f"Submission rejected: {grok_review['reason']}",
            "payout_failed": f"Verified but payout failed: {submission.get('payout_error', 'Unknown error')}"
        }.get(submission["status"], "Submitted.")
    })

# =============================================================================
# ENDPOINTS - ADMIN
# =============================================================================

@tasks_bp.route('/api/v1/tasks/<task_id>/submissions', methods=['GET'])
@require_admin
def list_submissions(task_id):
    """List all submissions for a task (admin only)."""
    # Parse task_id
    try:
        task_id_parsed = int(task_id)
    except ValueError:
        task_id_parsed = task_id
    
    submissions_data = load_submissions()
    # Match both int and string versions
    task_submissions = [s for s in submissions_data["submissions"] if str(s["task_id"]) == str(task_id_parsed)]
    
    return jsonify({
        "success": True,
        "task_id": task_id_parsed,
        "count": len(task_submissions),
        "submissions": task_submissions
    })

@tasks_bp.route('/api/v1/tasks/submissions', methods=['GET'])
@require_admin
def list_all_submissions():
    """List all submissions (admin only)."""
    submissions_data = load_submissions()
    
    # Optional status filter
    status = request.args.get('status')
    submissions = submissions_data["submissions"]
    
    if status:
        submissions = [s for s in submissions if s["status"] == status]
    
    return jsonify({
        "success": True,
        "count": len(submissions),
        "submissions": submissions
    })

@tasks_bp.route('/api/v1/tasks/external', methods=['GET'])
@require_admin
def list_external_tasks():
    """List all external tasks with full details (admin only)."""
    external_data = load_external_tasks()
    tasks = external_data.get("tasks", [])
    
    # Optional status filter
    status = request.args.get('status')  # open, completed, cancelled
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    
    # Calculate stats
    open_count = len([t for t in external_data.get("tasks", []) if t.get("status") == "open"])
    completed_count = len([t for t in external_data.get("tasks", []) if t.get("status") == "completed"])
    total_watt_posted = sum(t.get("amount", 0) for t in external_data.get("tasks", []))
    total_watt_paid = sum(t.get("amount", 0) for t in external_data.get("tasks", []) if t.get("status") == "completed")
    
    return jsonify({
        "success": True,
        "count": len(tasks),
        "stats": {
            "open": open_count,
            "completed": completed_count,
            "total_posted_watt": total_watt_posted,
            "total_paid_watt": total_watt_paid
        },
        "tasks": tasks
    })

@tasks_bp.route('/api/v1/tasks/<task_id>/approve/<submission_id>', methods=['POST'])
@require_admin
def approve_submission(task_id, submission_id):
    """Manually approve a submission and trigger payout (admin only)."""
    # Parse task_id for comparison
    try:
        task_id_parsed = int(task_id)
    except ValueError:
        task_id_parsed = task_id
    
    submissions_data = load_submissions()
    
    for sub in submissions_data["submissions"]:
        if sub["id"] == submission_id and str(sub["task_id"]) == str(task_id_parsed):
            if sub["status"] == "paid":
                return jsonify({"success": False, "error": "already_paid"}), 400
            
            # Get task for amount
            task = get_task_by_id(task_id_parsed)
            amount = task["amount"] if task else sub.get("amount", 0)
            
            # Send payout
            success, tx_or_error = send_watt_payout(sub["wallet"], amount)
            
            if success:
                sub["status"] = "paid"
                sub["tx_signature"] = tx_or_error
                sub["paid_at"] = datetime.utcnow().isoformat() + "Z"
                sub["approved_by"] = "admin"
                save_submissions(submissions_data)
                
                # Update external task if applicable
                if task and task.get("source") == "external":
                    external_data = load_external_tasks()
                    for ext_task in external_data.get("tasks", []):
                        if ext_task["id"] == task_id_parsed:
                            if task["type"] == "one-time":
                                ext_task["status"] = "completed"
                            ext_task["completed_by"] = sub["wallet"]
                            ext_task["completed_at"] = datetime.utcnow().isoformat() + "Z"
                            break
                    save_external_tasks(external_data)
                elif task and task.get("source") == "github":
                    # Post GitHub comment
                    comment = f"""## ✅ Task Completed - Admin Approved

**Submission ID:** `{submission_id}`
**Agent Wallet:** `{sub['wallet']}`
**Payout:** {amount:,} WATT
**TX:** [{tx_or_error[:16]}...](https://solscan.io/tx/{tx_or_error})

---
*Manually approved by admin*
"""
                    post_github_comment(task_id_parsed, comment)
                
                return jsonify({
                    "success": True,
                    "status": "paid",
                    "tx_signature": tx_or_error
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "payout_failed",
                    "message": tx_or_error
                }), 500
    
    return jsonify({"success": False, "error": "submission_not_found"}), 404

@tasks_bp.route('/api/v1/tasks/<task_id>/reject/<submission_id>', methods=['POST'])
@require_admin
def reject_submission(task_id, submission_id):
    """Manually reject a submission (admin only)."""
    # Parse task_id for comparison
    try:
        task_id_parsed = int(task_id)
    except ValueError:
        task_id_parsed = task_id
    
    data = request.get_json() or {}
    reason = data.get("reason", "Rejected by admin")
    
    submissions_data = load_submissions()
    
    for sub in submissions_data["submissions"]:
        if sub["id"] == submission_id and str(sub["task_id"]) == str(task_id_parsed):
            if sub["status"] == "paid":
                return jsonify({"success": False, "error": "already_paid"}), 400
            
            sub["status"] = "rejected"
            sub["reject_reason"] = reason
            sub["rejected_at"] = datetime.utcnow().isoformat() + "Z"
            save_submissions(submissions_data)
            
            return jsonify({
                "success": True,
                "status": "rejected",
                "reason": reason
            })
    
    return jsonify({"success": False, "error": "submission_not_found"}), 404
