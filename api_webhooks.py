"""
WattCoin GitHub Webhook Handler
POST /webhooks/github - Handle PR merge events

Listens for:
- pull_request (action: closed + merged = true)

On merge:
- Verifies PR passed Grok review
- Checks if PR references a bounty issue
- Extracts wallet from PR body
- Queues payout (manual approval required)
- Posts status comment
"""

import os
import json
import hmac
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify

from pr_security import (
    verify_github_signature,
    extract_wallet_from_pr_body,
    check_emergency_pause,
    log_security_event,
    load_json_data,
    save_json_data,
    DATA_DIR,
    REQUIRE_DOUBLE_APPROVAL
)

webhooks_bp = Blueprint('webhooks', __name__)

# =============================================================================
# CONFIG
# =============================================================================

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = "WattCoin-Org/wattcoin"

PR_REVIEWS_FILE = f"{DATA_DIR}/pr_reviews.json"
PR_PAYOUTS_FILE = f"{DATA_DIR}/pr_payouts.json"

# =============================================================================
# GITHUB HELPERS
# =============================================================================

def github_headers():
    """Get GitHub API headers."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

def get_bounty_amount(issue_number):
    """
    Fetch bounty amount from issue title.
    Returns: amount (int) or None
    """
    import re
    import requests
    
    try:
        url = f"https://api.github.com/repos/{REPO}/issues/{issue_number}"
        resp = requests.get(url, headers=github_headers(), timeout=10)
        
        if resp.status_code != 200:
            return None
        
        issue = resp.json()
        title = issue.get("title", "")
        
        # Extract amount like [BOUNTY: 100,000 WATT]
        match = re.search(r'(\d{1,3}(?:,?\d{3})*)\s*WATT', title, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(',', ''))
        
        return None
    except:
        return None

def post_github_comment(issue_number, comment):
    """Post a comment on a GitHub issue/PR."""
    import requests
    
    if not GITHUB_TOKEN:
        return False
    
    try:
        url = f"https://api.github.com/repos/{REPO}/issues/{issue_number}/comments"
        resp = requests.post(
            url,
            headers=github_headers(),
            json={"body": comment},
            timeout=15
        )
        return resp.status_code in [200, 201]
    except:
        return False

# =============================================================================
# PAYOUT QUEUE
# =============================================================================

def find_pr_review(pr_number):
    """Find review record for a PR."""
    reviews = load_json_data(PR_REVIEWS_FILE, default={"reviews": []})
    
    for review in reversed(reviews["reviews"]):
        if review.get("pr_number") == pr_number:
            return review
    
    return None

def queue_payout(pr_number, wallet, amount, bounty_issue_id, review_data):
    """
    Queue a payout for manual approval.
    Returns: payout_id
    """
    payouts = load_json_data(PR_PAYOUTS_FILE, default={"payouts": []})
    
    payout_id = len(payouts["payouts"]) + 1
    
    payout = {
        "id": payout_id,
        "pr_number": pr_number,
        "wallet": wallet,
        "amount": amount,
        "bounty_issue_id": bounty_issue_id,
        "status": "pending",
        "queued_at": datetime.utcnow().isoformat() + "Z",
        "approved_by": None,
        "approved_at": None,
        "tx_signature": None,
        "paid_at": None,
        "review_score": review_data.get("review", {}).get("score") if review_data else None,
        "requires_double_approval": REQUIRE_DOUBLE_APPROVAL,
        "approval_count": 0
    }
    
    payouts["payouts"].append(payout)
    save_json_data(PR_PAYOUTS_FILE, payouts)
    
    return payout_id

# =============================================================================
# WEBHOOK HANDLER
# =============================================================================

@webhooks_bp.route('/webhooks/github', methods=['POST'])
def github_webhook():
    """
    Handle GitHub webhook events.
    
    Expected events:
    - pull_request (closed + merged)
    """
    # Verify signature if secret is configured
    if GITHUB_WEBHOOK_SECRET:
        signature = request.headers.get('X-Hub-Signature-256', '')
        payload_body = request.get_data()
        
        if not verify_github_signature(payload_body, signature, GITHUB_WEBHOOK_SECRET):
            log_security_event("webhook_invalid_signature", {
                "ip": request.remote_addr,
                "headers": dict(request.headers)
            })
            return jsonify({"error": "Invalid signature"}), 403
    
    # Parse event
    event_type = request.headers.get('X-GitHub-Event')
    payload = request.get_json()
    
    if not payload:
        return jsonify({"error": "No payload"}), 400
    
    # Only handle pull_request events
    if event_type != 'pull_request':
        return jsonify({"message": f"Ignoring event type: {event_type}"}), 200
    
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    pr_number = pr.get("number")
    merged = pr.get("merged", False)
    
    # Only process when PR is closed AND merged
    if action != "closed" or not merged:
        return jsonify({"message": f"Ignoring action: {action}, merged: {merged}"}), 200
    
    # Check emergency pause
    is_paused, pause_type, pause_msg = check_emergency_pause()
    if is_paused and pause_type == "payouts":
        log_security_event("payout_blocked_pause", {
            "pr_number": pr_number,
            "reason": pause_msg
        })
        
        # Still return 200 to acknowledge webhook
        return jsonify({"message": "Payouts paused, no action taken"}), 200
    
    # Extract wallet from PR body
    pr_body = pr.get("body", "")
    wallet, wallet_error = extract_wallet_from_pr_body(pr_body)
    
    if wallet_error:
        # Post comment about missing wallet
        comment = f"""## ❌ Payout Failed

Unable to process payout: {wallet_error}

Please update the PR description with your wallet address in this format:
```
**Payout Wallet**: your_solana_address_here
```
"""
        post_github_comment(pr_number, comment)
        
        log_security_event("payout_failed", {
            "pr_number": pr_number,
            "reason": "missing_wallet",
            "error": wallet_error
        })
        
        return jsonify({"message": "Wallet not found in PR"}), 200
    
    # Find review record
    review_data = find_pr_review(pr_number)
    
    if not review_data:
        # No review found - post comment
        comment = f"""## ⚠️ No Review Found

This PR was merged but no Grok review was found in our system.

If you believe this is a bounty PR, please contact an admin to manually process the payout.
"""
        post_github_comment(pr_number, comment)
        
        log_security_event("payout_no_review", {
            "pr_number": pr_number,
            "wallet": wallet
        })
        
        return jsonify({"message": "No review found"}), 200
    
    # Check if review passed
    review_result = review_data.get("review", {})
    if not review_result.get("pass"):
        # Review failed - shouldn't have been merged
        comment = f"""## ⚠️ Review Did Not Pass

This PR was merged but the Grok review score was {review_result.get('score')}/10 (requires ≥8).

Payout has been flagged for manual admin review.
"""
        post_github_comment(pr_number, comment)
        
        log_security_event("payout_failed_review", {
            "pr_number": pr_number,
            "wallet": wallet,
            "score": review_result.get("score")
        })
        
        # Still queue it, but admin will see low score
    
    # Get bounty issue ID from review or PR references
    bounty_issue_id = review_data.get("bounty_issue_id")
    
    if not bounty_issue_id:
        # Try to find from PR body
        import re
        referenced = re.findall(r'(?:closes?|fixes?|resolves?)?\s*#(\d+)', pr_body, re.IGNORECASE)
        if referenced:
            # Take the first referenced issue
            bounty_issue_id = int(referenced[0])
    
    # Get bounty amount
    amount = None
    if bounty_issue_id:
        amount = get_bounty_amount(bounty_issue_id)
    
    if not amount:
        # No bounty amount found
        comment = f"""## ⚠️ No Bounty Amount Found

This PR was merged but we couldn't determine the bounty amount.

Referenced issue: {f'#{bounty_issue_id}' if bounty_issue_id else 'None found'}

An admin will review and process the payout manually if applicable.
"""
        post_github_comment(pr_number, comment)
        
        log_security_event("payout_no_amount", {
            "pr_number": pr_number,
            "wallet": wallet,
            "bounty_issue_id": bounty_issue_id
        })
        
        return jsonify({"message": "No bounty amount found"}), 200
    
    # Queue payout for manual approval
    payout_id = queue_payout(pr_number, wallet, amount, bounty_issue_id, review_data)
    
    # Post success comment
    approval_text = "two admin approvals" if REQUIRE_DOUBLE_APPROVAL else "admin approval"
    
    comment = f"""## 🎉 PR Merged - Payout Queued

**Bounty Amount**: {amount:,} WATT
**Payout Wallet**: `{wallet[:8]}...{wallet[-8:]}`
**Review Score**: {review_result.get('score', 'N/A')}/10
**Payout ID**: #{payout_id}

Your payout has been queued and is pending {approval_text}.

You will receive the WATT tokens once approved by a maintainer.

Thank you for your contribution! 🚀
"""
    
    post_github_comment(pr_number, comment)
    
    log_security_event("payout_queued", {
        "payout_id": payout_id,
        "pr_number": pr_number,
        "wallet": wallet,
        "amount": amount,
        "bounty_issue_id": bounty_issue_id
    })
    
    return jsonify({
        "message": "Payout queued",
        "payout_id": payout_id,
        "amount": amount,
        "wallet": wallet
    }), 200

# =============================================================================
# HEALTH CHECK
# =============================================================================

@webhooks_bp.route('/webhooks/health', methods=['GET'])
def webhook_health():
    """Simple health check for webhook endpoint."""
    return jsonify({
        "status": "ok",
        "webhook_secret_configured": bool(GITHUB_WEBHOOK_SECRET)
    }), 200
