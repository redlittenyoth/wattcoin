"""
WattCoin Skill - Pay and earn WATT tokens for agent tasks.

Setup:
    export WATT_WALLET_PRIVATE_KEY="your_base58_private_key"
    
Requirements:
    pip install solana solders requests base58
"""

import os
import json
import requests
import base58
from typing import Optional, Dict, Any

# =============================================================================
# CONSTANTS
# =============================================================================

WATT_MINT = "Gpmbh4PoQnL1kNgpMYDED3iv4fczcr7d3qNBLf8rpump"
API_BASE = "https://wattcoin-production-81a7.up.railway.app"
BOUNTY_WALLET = "7vvNkG3JF3JpxLEavqZSkc5T3n9hHR98Uw23fbWdXVSF"
TREASURY_WALLET = "Atu5phbGGGFogbKhi259czz887dSdTfXwJxwbuE5aF5q"
SOLANA_RPC = "https://solana.publicnode.com"
LLM_PRICE = 500  # WATT per query
SCRAPE_PRICE = 100  # WATT per scrape
WATT_DECIMALS = 6
MIN_TASK_REWARD = 500  # Minimum WATT for posting a task

# =============================================================================
# WALLET HANDLING
# =============================================================================

_wallet_cache = None

def _get_wallet():
    """Load wallet from environment or file."""
    global _wallet_cache
    if _wallet_cache:
        return _wallet_cache
    
    # Try environment variable first
    private_key = os.getenv("WATT_WALLET_PRIVATE_KEY")
    if private_key:
        try:
            from solders.keypair import Keypair
            key_bytes = base58.b58decode(private_key)
            _wallet_cache = Keypair.from_bytes(key_bytes)
            return _wallet_cache
        except Exception as e:
            raise RuntimeError(f"Failed to load wallet from WATT_WALLET_PRIVATE_KEY: {e}")
    
    # Try config file
    config_path = os.path.join(os.path.dirname(__file__), "config")
    if os.path.exists(config_path):
        try:
            from solders.keypair import Keypair
            with open(config_path) as f:
                data = json.load(f)
            key_bytes = base58.b58decode(data["private_key"])
            _wallet_cache = Keypair.from_bytes(key_bytes)
            return _wallet_cache
        except Exception as e:
            raise RuntimeError(f"Failed to load wallet from config file: {e}")
    
    raise RuntimeError(
        "No wallet configured. Set WATT_WALLET_PRIVATE_KEY environment variable "
        "or create a config file with your private key."
    )

def get_wallet_address() -> str:
    """Get the public key of the configured wallet."""
    wallet = _get_wallet()
    return str(wallet.pubkey())

def watt_balance() -> int:
    """
    Get current WATT balance.
    
    Returns:
        Integer balance (not decimals)
    """
    from solana.rpc.api import Client
    from solders.pubkey import Pubkey
    from spl.token.instructions import get_associated_token_address
    from spl.token.constants import TOKEN_2022_PROGRAM_ID
    
    wallet = _get_wallet()
    client = Client(SOLANA_RPC)
    
    mint = Pubkey.from_string(WATT_MINT)
    owner = wallet.pubkey()
    
    ata = get_associated_token_address(owner, mint, token_program_id=TOKEN_2022_PROGRAM_ID)
    
    try:
        resp = client.get_token_account_balance(ata)
        if resp.value:
            return int(resp.value.amount) // (10 ** WATT_DECIMALS)
        return 0
    except:
        return 0

# =============================================================================
# PAYMENTS
# =============================================================================

def watt_send(to: str, amount: int) -> str:
    """
    Send WATT to an address.
    
    Args:
        to: Recipient wallet address
        amount: Amount of WATT to send (integer, not decimals)
        
    Returns:
        Transaction signature
    """
    from solana.rpc.api import Client
    from solana.rpc.commitment import Confirmed
    from solders.transaction import Transaction
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.hash import Hash
    from spl.token.instructions import get_associated_token_address
    from spl.token.constants import TOKEN_2022_PROGRAM_ID
    import struct
    
    wallet = _get_wallet()
    client = Client(SOLANA_RPC)
    
    mint = Pubkey.from_string(WATT_MINT)
    from_pubkey = wallet.pubkey()
    to_pubkey = Pubkey.from_string(to)
    
    # Get associated token addresses
    from_ata = get_associated_token_address(from_pubkey, mint, token_program_id=TOKEN_2022_PROGRAM_ID)
    to_ata = get_associated_token_address(to_pubkey, mint, token_program_id=TOKEN_2022_PROGRAM_ID)
    
    # Build transfer instruction manually
    # SPL Token Transfer instruction: [3, amount (u64, little-endian)]
    amount_raw = amount * (10 ** WATT_DECIMALS)
    data = bytes([3]) + struct.pack("<Q", amount_raw)
    
    transfer_ix = Instruction(
        program_id=TOKEN_2022_PROGRAM_ID,
        accounts=[
            AccountMeta(pubkey=from_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=to_ata, is_signer=False, is_writable=True),
            AccountMeta(pubkey=from_pubkey, is_signer=True, is_writable=False),
        ],
        data=data
    )
    
    # Get recent blockhash
    blockhash_resp = client.get_latest_blockhash()
    recent_blockhash = Hash.from_string(str(blockhash_resp.value.blockhash))
    
    # Build message and transaction
    msg = Message.new_with_blockhash(
        [transfer_ix],
        from_pubkey,
        recent_blockhash
    )
    
    tx = Transaction.new_unsigned(msg)
    tx = Transaction([wallet], msg, recent_blockhash)
    
    # Send transaction
    result = client.send_transaction(tx)
    
    if result.value:
        return str(result.value)
    else:
        raise RuntimeError(f"Transaction failed: {result}")

# =============================================================================
# LLM QUERY
# =============================================================================

def watt_query(prompt: str) -> Dict[str, Any]:
    """
    Query Grok via LLM proxy. Auto-sends 500 WATT payment.
    
    Args:
        prompt: Question or prompt for Grok
        
    Returns:
        Dict with 'response', 'tokens_used', 'watt_charged', etc.
    """
    # Step 1: Send payment
    tx_sig = watt_send(BOUNTY_WALLET, LLM_PRICE)
    
    # Step 2: Wait for confirmation (give RPC time to sync)
    import time
    time.sleep(3)
    
    # Step 3: Call LLM API
    wallet = get_wallet_address()
    
    resp = requests.post(
        f"{API_BASE}/api/v1/llm",
        json={
            "prompt": prompt,
            "wallet": wallet,
            "tx_signature": tx_sig
        },
        timeout=60
    )
    
    data = resp.json()
    
    if not data.get("success"):
        raise RuntimeError(f"LLM query failed: {data.get('message', data.get('error', 'Unknown error'))}")
    
    return data

# =============================================================================
# SCRAPE
# =============================================================================

def watt_scrape(url: str, format: str = "text") -> Dict[str, Any]:
    """
    Scrape URL via WattCoin API. Auto-sends 100 WATT payment.
    
    Args:
        url: URL to scrape
        format: 'text', 'html', or 'json'
        
    Returns:
        Dict with 'content', 'url', 'watt_charged', etc.
    """
    # Step 1: Send payment
    tx_sig = watt_send(BOUNTY_WALLET, SCRAPE_PRICE)
    
    # Step 2: Wait for confirmation
    import time
    time.sleep(3)
    
    # Step 3: Call scraper API with payment proof
    wallet = get_wallet_address()
    
    resp = requests.post(
        f"{API_BASE}/api/v1/scrape",
        json={
            "url": url,
            "format": format,
            "wallet": wallet,
            "tx_signature": tx_sig
        },
        timeout=30
    )
    
    data = resp.json()
    
    if not data.get("success"):
        raise RuntimeError(f"Scrape failed: {data.get('message', data.get('error', 'Unknown error'))}")
    
    return data

# =============================================================================
# TASKS
# =============================================================================

def watt_tasks(task_type: Optional[str] = None, min_reward: Optional[int] = None) -> Dict[str, Any]:
    """
    Get available tasks from WattCoin network.
    
    Args:
        task_type: Filter by type ('bounty', 'agent', or None for all)
        min_reward: Filter by minimum WATT reward
        
    Returns:
        Dict with 'tasks' list
    """
    params = {}
    if task_type:
        params["type"] = task_type
    if min_reward:
        params["min_reward"] = min_reward
    
    resp = requests.get(f"{API_BASE}/api/v1/tasks", params=params, timeout=10)
    return resp.json()

def watt_submit(task_id: int, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit task result for verification and payout.
    
    Args:
        task_id: ID of the completed task
        result: Task result data (format depends on task type)
        
    Returns:
        Dict with 'success', 'watt_earned', 'tx_signature', etc.
    """
    wallet = get_wallet_address()
    
    resp = requests.post(
        f"{API_BASE}/api/v1/tasks/{task_id}/submit",
        json={
            "wallet": wallet,
            "result": result
        },
        timeout=30
    )
    
    data = resp.json()
    
    if not data.get("success"):
        raise RuntimeError(f"Task submission failed: {data.get('message', data.get('error', 'Unknown error'))}")
    
    return data

def watt_post_task(
    title: str,
    description: str,
    reward: int,
    verification_criteria: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Post a new task to the network (500+ WATT stake required).
    
    Args:
        title: Task title
        description: Task description
        reward: WATT reward for completion
        verification_criteria: Optional criteria for auto-verification
        
    Returns:
        Dict with 'task_id', 'tx_signature', etc.
    """
    if reward < MIN_TASK_REWARD:
        raise ValueError(f"Reward must be at least {MIN_TASK_REWARD} WATT")
    
    # Send stake payment
    tx_sig = watt_send(BOUNTY_WALLET, reward)
    
    # Wait for confirmation
    import time
    time.sleep(3)
    
    wallet = get_wallet_address()
    
    resp = requests.post(
        f"{API_BASE}/api/v1/tasks",
        json={
            "title": title,
            "description": description,
            "reward": reward,
            "wallet": wallet,
            "tx_signature": tx_sig,
            "verification_criteria": verification_criteria or {}
        },
        timeout=30
    )
    
    data = resp.json()
    
    if not data.get("success"):
        raise RuntimeError(f"Task posting failed: {data.get('message', data.get('error', 'Unknown error'))}")
    
    return data

# =============================================================================
# MAIN EXPORTS
# =============================================================================

__all__ = [
    "get_wallet_address",
    "watt_balance",
    "watt_send",
    "watt_query",
    "watt_scrape",
    "watt_tasks",
    "watt_submit",
    "watt_post_task",
]
