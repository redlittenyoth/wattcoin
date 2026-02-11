"""
WattCoin SuperIntelligence (WSI) - Phase 1: Distributed Inference
Gateway API that routes queries to inference swarm via seed/community nodes.

Endpoints:
- POST /api/v1/wsi/query      - Submit inference query (requires 5K WATT hold)
- POST /api/v1/wsi/status     - Check wallet access & usage
- GET  /api/v1/wsi/info       - System info & stats
- GET  /api/v1/wsi/swarm      - Live swarm health (nodes, models, capacity)
- GET  /api/v1/wsi/models     - Available models on the network
- POST /api/v1/wsi/contribute - Nodes report inference contributions

Version: 2.2.0
"""

import os
import json
import time
import requests as http_requests
from datetime import datetime
from flask import Blueprint, request, jsonify

wsi_bp = Blueprint('wsi', __name__)

# =============================================================================
# CONFIG
# =============================================================================

WATT_MINT = "Gpmbh4PoQnL1kNgpMYDED3iv4fczcr7d3qNBLf8rpump"
SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# WSI Gateway — seed node running inference client + HTTP gateway
WSI_GATEWAY_URL = os.getenv("WSI_GATEWAY_URL", "")  # e.g. http://seed-node-ip:8090
WSI_GATEWAY_TIMEOUT = int(os.getenv("WSI_GATEWAY_TIMEOUT", "120"))  # inference can be slow
WSI_GATEWAY_KEY = os.getenv("WSI_GATEWAY_KEY", "")  # shared secret for node contribution reports

# Access requirements (configurable via env vars)
MIN_WATT_BALANCE = int(os.environ.get('WSI_MIN_BALANCE', '5000'))   # Hold to access
DAILY_QUERY_LIMIT = int(os.environ.get('WSI_DAILY_LIMIT', '20'))    # Per wallet per 24h
HOURLY_LIMIT_WALLET = int(os.environ.get('WSI_HOURLY_LIMIT_WALLET', '10'))   # Per wallet per hour
HOURLY_LIMIT_GLOBAL = int(os.environ.get('WSI_HOURLY_LIMIT_GLOBAL', '100'))  # All wallets per hour
QUERY_COST_WATT = 0       # Phase 1: free queries for holders (burn/cost TBD)
CACHE_TTL = 300            # 5 min balance cache

# Data files
DATA_DIR = "data"
WSI_USAGE_FILE = f"{DATA_DIR}/wsi_usage.json"
WSI_CONTRIBUTIONS_FILE = f"{DATA_DIR}/wsi_contributions.json"
WSI_PAYOUT_QUEUE_FILE = f"{DATA_DIR}/wsi_payout_queue.json"

# Payout config (configurable via env vars)
WSI_QUERY_COST = int(os.environ.get('WSI_QUERY_COST', '50'))            # Total WATT cost per query
WSI_NODE_PAYOUT_PCT = int(os.environ.get('WSI_NODE_PAYOUT_PCT', '70'))  # % to node operator (remainder to treasury)

# =============================================================================
# BALANCE CHECKING
# =============================================================================

_balance_cache = {}  # wallet -> (balance, expires_at)

# =============================================================================
# HOURLY RATE LIMITING (in-memory, resets on restart)
# =============================================================================

_hourly_queries_wallet = {}  # wallet -> [timestamp, timestamp, ...]
_hourly_queries_global = []  # [timestamp, timestamp, ...]


def _cleanup_hourly():
    """Remove entries older than 1 hour."""
    cutoff = time.time() - 3600
    # Clean global
    global _hourly_queries_global
    _hourly_queries_global = [t for t in _hourly_queries_global if t > cutoff]
    # Clean per-wallet
    expired_wallets = []
    for wallet, timestamps in _hourly_queries_wallet.items():
        _hourly_queries_wallet[wallet] = [t for t in timestamps if t > cutoff]
        if not _hourly_queries_wallet[wallet]:
            expired_wallets.append(wallet)
    for w in expired_wallets:
        del _hourly_queries_wallet[w]


def check_hourly_limits(wallet):
    """
    Check hourly rate limits (global and per-wallet).
    Returns: (is_allowed, reason) — reason is None if allowed.
    """
    _cleanup_hourly()

    # Global limit
    if len(_hourly_queries_global) >= HOURLY_LIMIT_GLOBAL:
        return False, f"Global hourly limit reached ({HOURLY_LIMIT_GLOBAL}/hr). Try again shortly."

    # Per-wallet limit
    wallet_count = len(_hourly_queries_wallet.get(wallet, []))
    if wallet_count >= HOURLY_LIMIT_WALLET:
        return False, f"Wallet hourly limit reached ({HOURLY_LIMIT_WALLET}/hr). Try again shortly."

    return True, None


def record_hourly_query(wallet):
    """Record a query for hourly rate tracking."""
    now = time.time()
    _hourly_queries_global.append(now)
    if wallet not in _hourly_queries_wallet:
        _hourly_queries_wallet[wallet] = []
    _hourly_queries_wallet[wallet].append(now)


def get_watt_balance(wallet):
    """
    Check WATT balance for a wallet.
    Returns: (balance, error)
    """
    now = time.time()
    if wallet in _balance_cache:
        balance, expires = _balance_cache[wallet]
        if now < expires:
            return balance, None

    try:
        resp = http_requests.post(SOLANA_RPC, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet,
                {"mint": WATT_MINT},
                {"encoding": "jsonParsed"}
            ]
        }, timeout=15)

        data = resp.json()

        if "error" in data:
            return 0, f"RPC error: {data['error'].get('message', 'Unknown')}"

        accounts = data.get("result", {}).get("value", [])

        if not accounts:
            return 0, None

        token_amount = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
        balance = int(token_amount["amount"]) / (10 ** 6)  # 6 decimals

        _balance_cache[wallet] = (balance, now + CACHE_TTL)
        return balance, None

    except Exception as e:
        return 0, f"Balance check failed: {e}"


# =============================================================================
# USAGE TRACKING
# =============================================================================

def load_json(filepath, default):
    """Generic JSON file loader."""
    if not os.path.exists(filepath):
        return default.copy()
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return default.copy()


def save_json(filepath, data):
    """Generic JSON file saver."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def check_daily_limit(wallet):
    """
    Check if wallet has exceeded daily query limit.
    Returns: (is_allowed, used_count, limit)
    """
    usage_data = load_json(WSI_USAGE_FILE, {"queries": []})
    now = time.time()
    one_day_ago = now - (24 * 3600)

    recent_queries = [
        q for q in usage_data.get("queries", [])
        if q.get("wallet") == wallet and q.get("timestamp", 0) > one_day_ago
    ]

    used_count = len(recent_queries)
    is_allowed = used_count < DAILY_QUERY_LIMIT
    return is_allowed, used_count, DAILY_QUERY_LIMIT


def record_query(wallet, prompt, response_text, model, gateway_meta, latency_ms):
    """Record a completed query for usage tracking."""
    usage_data = load_json(WSI_USAGE_FILE, {"queries": []})

    query_record = {
        "query_id": f"wsi_{int(time.time())}_{wallet[:8]}",
        "wallet": wallet,
        "timestamp": time.time(),
        "date": datetime.utcnow().isoformat() + "Z",
        "prompt_length": len(prompt),
        "response_length": len(response_text),
        "model": model,
        "latency_ms": latency_ms,
        "nodes_used": gateway_meta.get("nodes_used", []),
        "blocks_served": gateway_meta.get("total_blocks", 0),
        "tokens_generated": gateway_meta.get("tokens_generated", 0)
    }

    usage_data["queries"].append(query_record)

    # Keep only last 10,000 queries
    if len(usage_data["queries"]) > 10000:
        usage_data["queries"] = usage_data["queries"][-10000:]

    save_json(WSI_USAGE_FILE, usage_data)
    return query_record["query_id"]


# =============================================================================
# CONTRIBUTION TRACKING & PAYOUT QUEUE
# =============================================================================

def record_contribution(node_id, wallet, query_id, blocks_served, latency_ms, model):
    """Record a node's contribution to a query and queue payout."""
    # Record contribution
    data = load_json(WSI_CONTRIBUTIONS_FILE, {"contributions": []})

    data["contributions"].append({
        "node_id": node_id,
        "wallet": wallet,
        "query_id": query_id,
        "blocks_served": blocks_served,
        "latency_ms": latency_ms,
        "model": model,
        "timestamp": time.time(),
        "date": datetime.utcnow().isoformat() + "Z"
    })

    # Keep last 50,000
    if len(data["contributions"]) > 50000:
        data["contributions"] = data["contributions"][-50000:]

    save_json(WSI_CONTRIBUTIONS_FILE, data)

    # Queue payout — proportional to blocks served
    # For now, simple: flat reward per query, split if multiple nodes
    queue_inference_payout(node_id, wallet, query_id, blocks_served)


def queue_inference_payout(node_id, wallet, query_id, blocks_served):
    """Add inference payout to queue for batch processing."""
    queue = load_json(WSI_PAYOUT_QUEUE_FILE, {"pending": [], "processed": []})

    node_reward = WSI_QUERY_COST * WSI_NODE_PAYOUT_PCT // 100
    treasury_share = WSI_QUERY_COST - node_reward

    queue["pending"].append({
        "node_id": node_id,
        "wallet": wallet,
        "query_id": query_id,
        "blocks_served": blocks_served,
        "reward_watt": node_reward,
        "treasury_watt": treasury_share,
        "query_cost": WSI_QUERY_COST,
        "payout_pct": WSI_NODE_PAYOUT_PCT,
        "queued_at": time.time(),
        "date": datetime.utcnow().isoformat() + "Z",
        "status": "pending"
    })

    save_json(WSI_PAYOUT_QUEUE_FILE, queue)


# =============================================================================
# GATEWAY COMMUNICATION
# =============================================================================

def query_gateway(prompt, model=None, max_tokens=500, temperature=0.7):
    """
    Forward inference request to inference gateway node.

    The gateway runs the inference client which routes the query through
    the distributed swarm of nodes hosting model layers.

    Returns: (result_dict, error_string)
    """
    if not WSI_GATEWAY_URL:
        return None, "WSI network offline — gateway not configured"

    try:
        resp = http_requests.post(
            f"{WSI_GATEWAY_URL}/inference",
            json={
                "prompt": prompt,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature
            },
            timeout=WSI_GATEWAY_TIMEOUT
        )

        if resp.status_code != 200:
            return None, f"Gateway error (HTTP {resp.status_code}): {resp.text[:200]}"

        result = resp.json()
        if not result.get("success"):
            return None, result.get("error", "Unknown gateway error")

        return result, None

    except http_requests.ConnectionError:
        return None, "Cannot reach WSI network. The swarm may be offline."
    except http_requests.Timeout:
        return None, f"Inference timeout after {WSI_GATEWAY_TIMEOUT}s. Try a shorter prompt."
    except Exception as e:
        return None, f"Gateway communication error: {e}"


def get_swarm_status():
    """Get live swarm health from gateway node."""
    if not WSI_GATEWAY_URL:
        return {"online": False, "reason": "Gateway not configured"}, None

    try:
        resp = http_requests.get(f"{WSI_GATEWAY_URL}/swarm", timeout=15)
        if resp.status_code == 200:
            return resp.json(), None
        return {"online": False, "reason": f"HTTP {resp.status_code}"}, None
    except Exception as e:
        return {"online": False, "reason": str(e)}, None


def get_available_models():
    """Get list of models available on the swarm."""
    if not WSI_GATEWAY_URL:
        return [], None

    try:
        resp = http_requests.get(f"{WSI_GATEWAY_URL}/models", timeout=15)
        if resp.status_code == 200:
            return resp.json().get("models", []), None
        return [], None
    except Exception:
        return [], None


# =============================================================================
# DISCORD NOTIFICATIONS
# =============================================================================

def notify_wsi_discord(title, message, color=0x9B59B6, fields=None):
    """Send WSI event to Discord (purple theme for WSI)."""
    try:
        from api_webhooks import notify_discord
        notify_discord(title, message, color=color, fields=fields)
    except ImportError:
        pass


# =============================================================================
# ENDPOINTS
# =============================================================================

@wsi_bp.route('/api/v1/wsi/query', methods=['POST'])
def wsi_query():
    """
    Submit an inference query to the WSI distributed network.

    Body:
    {
      "wallet": "solana_address",
      "prompt": "your question or instruction",
      "model": null,            // optional — uses default swarm model
      "max_tokens": 500,        // optional
      "temperature": 0.7        // optional
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Request body required"}), 400

    wallet = data.get("wallet", "").strip()
    prompt = data.get("prompt", "").strip()
    model = data.get("model")
    max_tokens = min(data.get("max_tokens", 500), 2000)  # cap at 2000
    temperature = data.get("temperature", 0.7)

    if not wallet:
        return jsonify({"success": False, "error": "wallet address required"}), 400

    if not prompt:
        return jsonify({"success": False, "error": "prompt required"}), 400

    if len(prompt) > 10000:
        return jsonify({"success": False, "error": "Prompt too long (max 10,000 chars)"}), 400

    # Check balance
    balance, balance_error = get_watt_balance(wallet)
    if balance_error:
        return jsonify({"success": False, "error": balance_error}), 500

    if balance < MIN_WATT_BALANCE:
        return jsonify({
            "success": False,
            "error": f"Insufficient WATT balance. Hold {MIN_WATT_BALANCE:,} WATT to access WSI.",
            "required_balance": MIN_WATT_BALANCE,
            "current_balance": balance
        }), 403

    # Check hourly rate limits
    hourly_allowed, hourly_reason = check_hourly_limits(wallet)
    if not hourly_allowed:
        return jsonify({
            "success": False,
            "error": hourly_reason
        }), 429

    # Check daily limit
    is_allowed, used_count, limit = check_daily_limit(wallet)
    if not is_allowed:
        return jsonify({
            "success": False,
            "error": f"Daily query limit reached ({limit} per 24h)",
            "queries_used": used_count,
            "queries_limit": limit
        }), 429

    # Forward to inference gateway
    start_time = time.time()
    result, error = query_gateway(prompt, model=model, max_tokens=max_tokens, temperature=temperature)
    latency_ms = int((time.time() - start_time) * 1000)

    if error:
        return jsonify({"success": False, "error": error}), 503

    response_text = result.get("response", "")
    actual_model = result.get("model", "unknown")
    gateway_meta = {
        "nodes_used": result.get("nodes_used", []),
        "total_blocks": result.get("total_blocks", 0),
        "tokens_generated": result.get("tokens_generated", 0)
    }

    # Record usage
    query_id = record_query(wallet, prompt, response_text, actual_model, gateway_meta, latency_ms)
    record_hourly_query(wallet)

    # Record node contributions from gateway response (if reported)
    for node_info in result.get("contributions", []):
        record_contribution(
            node_id=node_info.get("node_id", "unknown"),
            wallet=node_info.get("wallet", ""),
            query_id=query_id,
            blocks_served=node_info.get("blocks_served", 0),
            latency_ms=node_info.get("latency_ms", 0),
            model=actual_model
        )

    queries_remaining = limit - (used_count + 1)

    return jsonify({
        "success": True,
        "query_id": query_id,
        "response": response_text,
        "model": actual_model,
        "tokens_generated": gateway_meta["tokens_generated"],
        "latency_ms": latency_ms,
        "served_by": gateway_meta["nodes_used"],
        "queries_used": used_count + 1,
        "queries_remaining": queries_remaining
    }), 200


# Legacy chat endpoint — redirect to query
@wsi_bp.route('/api/v1/wsi/chat', methods=['POST'])
def wsi_chat():
    """Legacy chat endpoint. Translates to query format for backwards compatibility."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Request body required"}), 400

    # Translate chat format to query format
    query_data = {
        "wallet": data.get("wallet", ""),
        "prompt": data.get("message", ""),
        "max_tokens": 2000,
        "temperature": 0.7
    }

    # Forward internally
    with wsi_bp.test_request_context(
        '/api/v1/wsi/query',
        method='POST',
        json=query_data,
        content_type='application/json'
    ):
        # Just redirect to the new endpoint
        pass

    # Simpler: just call gateway directly with same auth checks
    wallet = data.get("wallet", "").strip()
    message = data.get("message", "").strip()

    if not wallet or not message:
        return jsonify({"success": False, "error": "wallet and message required"}), 400

    balance, err = get_watt_balance(wallet)
    if err:
        return jsonify({"success": False, "error": err}), 500
    if balance < MIN_WATT_BALANCE:
        return jsonify({"success": False, "error": "Insufficient WATT balance"}), 403

    is_allowed, used_count, limit = check_daily_limit(wallet)
    if not is_allowed:
        return jsonify({"success": False, "error": "Daily limit exceeded"}), 429

    hourly_allowed, hourly_reason = check_hourly_limits(wallet)
    if not hourly_allowed:
        return jsonify({"success": False, "error": hourly_reason}), 429

    start_time = time.time()
    result, error = query_gateway(message, max_tokens=2000)
    latency_ms = int((time.time() - start_time) * 1000)

    if error:
        return jsonify({"success": False, "error": error}), 503

    response_text = result.get("response", "")
    record_query(wallet, message, response_text, result.get("model", ""), {}, latency_ms)
    record_hourly_query(wallet)

    return jsonify({
        "success": True,
        "response": response_text,
        "queries_remaining": limit - (used_count + 1)
    }), 200


@wsi_bp.route('/api/v1/wsi/status', methods=['POST'])
def wsi_status():
    """
    Check WSI access status for a wallet.

    Body: { "wallet": "solana_address" }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    wallet = data.get("wallet", "").strip()
    if not wallet:
        return jsonify({"error": "wallet required"}), 400

    balance, balance_error = get_watt_balance(wallet)
    if balance_error:
        return jsonify({"error": balance_error}), 500

    is_allowed, used_count, limit = check_daily_limit(wallet)
    has_access = balance >= MIN_WATT_BALANCE and is_allowed

    # Check if swarm is online
    swarm_status, _ = get_swarm_status()
    swarm_online = swarm_status.get("online", False) if swarm_status else False

    return jsonify({
        "has_access": has_access,
        "balance": balance,
        "required_balance": MIN_WATT_BALANCE,
        "queries_used": used_count,
        "queries_remaining": max(0, limit - used_count),
        "queries_limit": limit,
        "swarm_online": swarm_online,
        "reason": None if has_access else (
            "Insufficient balance" if balance < MIN_WATT_BALANCE else "Daily limit exceeded"
        )
    }), 200


@wsi_bp.route('/api/v1/wsi/info', methods=['GET'])
def wsi_info():
    """Get WSI system information and stats."""
    usage_data = load_json(WSI_USAGE_FILE, {"queries": []})
    contrib_data = load_json(WSI_CONTRIBUTIONS_FILE, {"contributions": []})
    payout_data = load_json(WSI_PAYOUT_QUEUE_FILE, {"pending": [], "processed": []})

    total_queries = len(usage_data.get("queries", []))
    total_contributions = len(contrib_data.get("contributions", []))
    pending_payouts = len(payout_data.get("pending", []))

    # Queries in last 24h
    now = time.time()
    one_day_ago = now - (24 * 3600)
    recent_queries = [
        q for q in usage_data.get("queries", [])
        if q.get("timestamp", 0) > one_day_ago
    ]

    # Unique nodes that contributed
    unique_nodes = set(
        c.get("node_id") for c in contrib_data.get("contributions", [])
    )

    return jsonify({
        "system": "WattCoin SuperIntelligence (WSI)",
        "version": "2.2.0",
        "phase": "Phase 1: Distributed Inference",
        "architecture": "Distributed swarm — model layers distributed across WattNode operators",
        "requirements": {
            "min_balance": MIN_WATT_BALANCE,
            "daily_limit": DAILY_QUERY_LIMIT,
            "query_cost": QUERY_COST_WATT
        },
        "stats": {
            "total_queries": total_queries,
            "queries_24h": len(recent_queries),
            "total_contributions": total_contributions,
            "unique_nodes_served": len(unique_nodes),
            "pending_payouts": pending_payouts
        },
        "gateway_configured": bool(WSI_GATEWAY_URL),
        "status": "operational" if WSI_GATEWAY_URL else "awaiting_gateway"
    }), 200


@wsi_bp.route('/api/v1/wsi/swarm', methods=['GET'])
def wsi_swarm():
    """Get live swarm health — nodes, models, capacity."""
    swarm_status, error = get_swarm_status()

    if error:
        return jsonify({
            "online": False,
            "error": error,
            "message": "WSI swarm is not yet online. Seed node setup in progress."
        }), 200  # 200 not 503 — this is informational

    return jsonify(swarm_status), 200


@wsi_bp.route('/api/v1/wsi/models', methods=['GET'])
def wsi_models():
    """Get available models on the swarm."""
    models, error = get_available_models()

    return jsonify({
        "models": models,
        "default": models[0] if models else None,
        "count": len(models),
        "error": error
    }), 200


@wsi_bp.route('/api/v1/wsi/contribute', methods=['POST'])
def wsi_contribute():
    """
    Node reports inference contribution after serving blocks.
    Called by the inference gateway or WattNode after completing inference work.

    Body:
    {
      "gateway_key": "shared_secret",
      "node_id": "node_abc123",
      "wallet": "solana_wallet",
      "query_id": "wsi_1234567890_abc",
      "blocks_served": 10,
      "latency_ms": 450,
      "model": "meta-llama/Meta-Llama-3.1-8B-Instruct"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Request body required"}), 400

    # Auth check — shared secret between gateway and Railway API
    # FAIL-CLOSED: If no key configured, endpoint is disabled (not open)
    if not WSI_GATEWAY_KEY:
        return jsonify({"success": False, "error": "WSI contributions disabled — gateway key not configured"}), 503
    if data.get("gateway_key") != WSI_GATEWAY_KEY:
        return jsonify({"success": False, "error": "Invalid gateway key"}), 403

    node_id = data.get("node_id", "").strip()
    wallet = data.get("wallet", "").strip()
    query_id = data.get("query_id", "").strip()
    blocks_served = data.get("blocks_served", 0)
    latency_ms = data.get("latency_ms", 0)
    model = data.get("model", "unknown")

    if not node_id or not wallet or not query_id:
        return jsonify({"success": False, "error": "node_id, wallet, and query_id required"}), 400

    if blocks_served <= 0:
        return jsonify({"success": False, "error": "blocks_served must be > 0"}), 400

    record_contribution(node_id, wallet, query_id, blocks_served, latency_ms, model)

    # Sanitize model name for public Discord — strip vendor org prefix (e.g., "Qwen/Qwen2.5-7B-Instruct" → "7B-Instruct")
    display_model = model.split("/")[-1] if model else "unknown"
    # Also strip common model family prefixes for cleaner display
    for prefix in ["Qwen2.5-", "Qwen2-", "Meta-Llama-", "Llama-"]:
        if display_model.startswith(prefix):
            display_model = display_model[len(prefix):]
            break

    notify_wsi_discord(
        "🧠 WSI Inference Contribution",
        f"Node `{node_id[:16]}` served {blocks_served} blocks for query `{query_id}`",
        color=0x9B59B6,
        fields={"Model": display_model, "Latency": f"{latency_ms}ms", "Reward": f"{WSI_QUERY_COST * WSI_NODE_PAYOUT_PCT // 100} WATT ({WSI_NODE_PAYOUT_PCT}%)"}
    )

    return jsonify({
        "success": True,
        "message": "Contribution recorded and payout queued",
        "reward_watt": WSI_QUERY_COST * WSI_NODE_PAYOUT_PCT // 100
    }), 200


# =============================================================================
# WSI PAYOUT QUEUE PROCESSOR
# =============================================================================

def process_wsi_payout_queue():
    """
    Process pending WSI inference payouts from wsi_payout_queue.json.
    Called on startup and periodically via timer.
    
    FAIL-CLOSED: If Solana RPC is down, bounty wallet has insufficient SOL,
    or any error occurs — entries stay in pending for next cycle. Never dropped.
    """
    from datetime import datetime
    
    queue = load_json(WSI_PAYOUT_QUEUE_FILE, {"pending": [], "processed": []})
    pending = [p for p in queue.get("pending", []) if p.get("status", "pending") == "pending"]
    
    if not pending:
        return
    
    print(f"[WSI-QUEUE] Processing {len(pending)} pending WSI payout(s)...", flush=True)
    
    # Import the payment executor from the bounty system
    try:
        from api_webhooks import execute_auto_payment
    except ImportError as e:
        print(f"[WSI-QUEUE] ❌ Cannot import payment executor: {e}", flush=True)
        return
    
    processed_count = 0
    failed_count = 0
    
    for entry in pending:
        node_id = entry.get("node_id", "unknown")
        wallet = entry.get("wallet", "")
        query_id = entry.get("query_id", "")
        reward = entry.get("reward_watt", 0)
        
        if not wallet or reward <= 0:
            # Invalid entry — mark as failed, don't retry
            entry["status"] = "failed"
            entry["error"] = "Invalid wallet or zero reward"
            entry["failed_at"] = datetime.utcnow().isoformat() + "Z"
            print(f"[WSI-QUEUE] ⚠️ Skipping invalid entry: {query_id}", flush=True)
            continue
        
        # Check retry count — max 3 attempts
        retry_count = entry.get("retry_count", 0)
        if retry_count >= 3:
            entry["status"] = "failed"
            entry["error"] = "Max retries (3) exhausted"
            entry["failed_at"] = datetime.utcnow().isoformat() + "Z"
            failed_count += 1
            
            notify_wsi_discord(
                "❌ WSI Payout Failed",
                f"Node `{node_id[:16]}` — {reward} WATT to `{wallet[:8]}...`\nMax retries exhausted for query `{query_id}`",
                color=0xFF0000
            )
            print(f"[WSI-QUEUE] ❌ Max retries for {query_id}", flush=True)
            continue
        
        print(f"[WSI-QUEUE] Processing: {reward} WATT to {wallet[:8]}... (query: {query_id})", flush=True)
        
        try:
            # Build WSI-specific on-chain memo
            wsi_memo = f"WSI Payout | Node: {node_id[:16]} | Query: {query_id} | {reward} WATT"
            
            tx_sig, error = execute_auto_payment(
                pr_number=0,  # No PR — WSI payout
                wallet=wallet,
                amount=reward,
                bounty_issue_id=None,
                review_score=None,
                memo_override=wsi_memo
            )
            
            if tx_sig and not error:
                # Success
                entry["status"] = "processed"
                entry["tx_signature"] = tx_sig
                entry["processed_at"] = datetime.utcnow().isoformat() + "Z"
                processed_count += 1
                
                # Move to processed list
                queue["processed"].append(entry)
                
                notify_wsi_discord(
                    "💰 WSI Payout Sent",
                    f"Node `{node_id[:16]}` earned **{reward} WATT**\n"
                    f"[View on Solscan](https://solscan.io/tx/{tx_sig})",
                    color=0x00FF00,
                    fields={
                        "Query": query_id,
                        "Split": f"{entry.get('payout_pct', 70)}% node / {100 - entry.get('payout_pct', 70)}% treasury",
                        "TX": f"{tx_sig[:16]}..."
                    }
                )
                print(f"[WSI-QUEUE] ✅ Paid {reward} WATT — TX: {tx_sig[:16]}...", flush=True)
                
            elif tx_sig and error:
                # TX sent but confirmation uncertain — mark with signature, retry
                entry["status"] = "pending"
                entry["retry_count"] = retry_count + 1
                entry["last_tx_attempt"] = tx_sig
                entry["last_error"] = str(error)
                entry["last_retry_at"] = datetime.utcnow().isoformat() + "Z"
                print(f"[WSI-QUEUE] ⚠️ TX sent but unconfirmed: {tx_sig[:16]}... — will retry", flush=True)
                
            else:
                # Failed — leave in pending for retry (FAIL-CLOSED)
                entry["status"] = "pending"
                entry["retry_count"] = retry_count + 1
                entry["last_error"] = str(error)
                entry["last_retry_at"] = datetime.utcnow().isoformat() + "Z"
                failed_count += 1
                print(f"[WSI-QUEUE] ⚠️ Payout failed: {error} — retry {retry_count + 1}/3", flush=True)
                
        except Exception as e:
            # Any exception — leave in pending (FAIL-CLOSED)
            entry["status"] = "pending"
            entry["retry_count"] = retry_count + 1
            entry["last_error"] = str(e)
            entry["last_retry_at"] = datetime.utcnow().isoformat() + "Z"
            failed_count += 1
            print(f"[WSI-QUEUE] ❌ Exception: {e} — retry {retry_count + 1}/3", flush=True)
    
    # Remove processed entries from pending list
    queue["pending"] = [p for p in queue["pending"] if p.get("status") == "pending"]
    
    # Also move failed entries out of pending
    failed_entries = [p for p in queue.get("pending", []) if p.get("status") == "failed"]
    for f in failed_entries:
        queue["processed"].append(f)
    queue["pending"] = [p for p in queue["pending"] if p.get("status") not in ("processed", "failed")]
    
    # Keep processed list manageable (last 1000)
    if len(queue.get("processed", [])) > 1000:
        queue["processed"] = queue["processed"][-1000:]
    
    save_json(WSI_PAYOUT_QUEUE_FILE, queue)
    
    print(f"[WSI-QUEUE] Done — {processed_count} paid, {failed_count} failed/retrying, {len(queue['pending'])} remaining", flush=True)


# =============================================================================
# HEALTH
# =============================================================================

@wsi_bp.route('/api/v1/wsi/health', methods=['GET'])
def wsi_health():
    """Health check for WSI service."""
    return jsonify({
        "service": "wsi",
        "version": "2.2.0",
        "gateway_configured": bool(WSI_GATEWAY_URL),
        "status": "ok"
    }), 200

