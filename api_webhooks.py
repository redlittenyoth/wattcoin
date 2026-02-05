"""
WattCoin GitHub Webhook Handler
POST /webhooks/github - Handle PR events with full automation

Listens for:
- pull_request (action: opened) → Auto-trigger Grok review
- pull_request (action: synchronize) → Auto-trigger Grok review on updates
- pull_request (action: closed + merged = true) → Auto-execute payment

Full Automation Flow:
1. PR opened → Grok reviews code automatically
2. If score ≥ 85% → Auto-merge PR
3. On merge → Auto-execute payment via bounty_auto_pay.py
4. Post TX signature to PR comments

Fallback: If auto-payment fails, queues for manual approval.
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
BASE_URL = os.getenv("BASE_URL", "https://wattcoin-production-81a7.up.railway.app")  # For internal API calls
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
# AUTO-REVIEW & AUTO-MERGE
# =============================================================================

def trigger_grok_review(pr_number):
    """
    Trigger Grok review for a PR.
    Calls the review endpoint internally.
    Returns: (review_result, error)
    """
    import requests
    
    try:
        # Call internal review endpoint
        base_url = os.getenv("BASE_URL", "http://localhost:5000")
        review_url = f"{base_url}/api/v1/review_pr"
        
        # Review endpoint expects pr_url, not pr_number
        pr_url = f"https://github.com/{REPO}/pull/{pr_number}"
        
        resp = requests.post(
            review_url,
            json={"pr_url": pr_url},
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        if resp.status_code == 200:
            return resp.json(), None
        else:
            return None, f"Review failed: {resp.status_code}"
    
    except Exception as e:
        return None, f"Review error: {e}"

def auto_merge_pr(pr_number, review_score):
    """
    Auto-merge a PR if it passes threshold.
    Returns: (success, error)
    """
    import requests
    
    MERGE_THRESHOLD = 85  # Require 85% score for auto-merge
    
    if review_score < MERGE_THRESHOLD:
        return False, f"Score {review_score} < {MERGE_THRESHOLD} threshold"
    
    try:
        url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}/merge"
        resp = requests.put(
            url,
            headers=github_headers(),
            json={
                "commit_title": f"Auto-merge PR #{pr_number} (Grok score: {review_score}/100)",
                "commit_message": f"Automatically merged after passing Grok review with score {review_score}/100",
                "merge_method": "squash"
            },
            timeout=15
        )
        
        if resp.status_code == 200:
            return True, None
        else:
            return False, f"Merge failed: {resp.status_code} - {resp.text}"
    
    except Exception as e:
        return False, f"Merge error: {e}"

def execute_auto_payment(pr_number, wallet, amount):
    """
    Execute payment automatically using bounty_auto_pay.py
    Returns: (tx_signature, error)
    """
    import subprocess
    
    try:
        # Call bounty_auto_pay.py script
        result = subprocess.run(
            ["python3", "bounty_auto_pay.py", str(pr_number)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Extract TX signature from output
            output = result.stdout
            import re
            tx_match = re.search(r'TX: ([A-Za-z0-9]{87,88})', output)
            if tx_match:
                return tx_match.group(1), None
            else:
                return "success", None  # Payment succeeded but couldn't extract TX
        else:
            return None, f"Payment failed: {result.stderr}"
    
    except Exception as e:
        return None, f"Payment error: {e}"

def handle_pr_review_trigger(pr_number, action):
    """
    Handle PR opened or synchronized - trigger Grok review and auto-merge if passed.
    """
    log_security_event("pr_review_triggered", {
        "pr_number": pr_number,
        "action": action
    })
    
    # Post initial comment
    post_github_comment(pr_number, "🤖 **Grok review triggered...** Analyzing code changes...")
    
    # Trigger Grok review
    review_result, review_error = trigger_grok_review(pr_number)
    
    if review_error:
        post_github_comment(pr_number, f"❌ **Review failed:** {review_error}")
        return jsonify({"message": "Review failed", "error": review_error}), 500
    
    review_data = review_result.get("review", {})
    score = review_data.get("score", 0)
    passed = review_data.get("pass", False)
    
    # If review passed threshold, auto-merge
    if passed and score >= 85:
        # Attempt auto-merge
        merged, merge_error = auto_merge_pr(pr_number, score)
        
        if merged:
            post_github_comment(
                pr_number,
                f"✅ **Auto-merged!** Grok score: {score}/100\n\n"
                f"Payment will be processed automatically after merge completes."
            )
            
            log_security_event("pr_auto_merged", {
                "pr_number": pr_number,
                "score": score
            })
        else:
            post_github_comment(
                pr_number,
                f"⚠️ **Review passed** (score: {score}/100) but auto-merge failed: {merge_error}\n\n"
                f"Please merge manually."
            )
    
    return jsonify({
        "message": "Review completed",
        "score": score,
        "passed": passed,
        "auto_merged": passed and score >= 85
    }), 200

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
    
    # Handle PR opened or synchronized (updated) - trigger auto-review
    if action in ["opened", "synchronize"]:
        return handle_pr_review_trigger(pr_number, action)
    
    # Only process merge events below this point
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
    
    # Execute payment automatically
    post_github_comment(pr_number, f"🚀 **Processing payment...** {amount:,} WATT to `{wallet[:8]}...{wallet[-8:]}`")
    
    tx_signature, payment_error = execute_auto_payment(pr_number, wallet, amount)
    
    if payment_error:
        # Payment failed - queue for manual review
        payout_id = queue_payout(pr_number, wallet, amount, bounty_issue_id, review_data)
        
        comment = f"""## ⚠️ Auto-Payment Failed

**Bounty Amount**: {amount:,} WATT
**Payout Wallet**: `{wallet[:8]}...{wallet[-8:]}`
**Error**: {payment_error}

Your payout has been queued (#{payout_id}) for manual processing by an admin.
"""
        post_github_comment(pr_number, comment)
        
        log_security_event("auto_payment_failed", {
            "pr_number": pr_number,
            "wallet": wallet,
            "amount": amount,
            "error": payment_error,
            "payout_id": payout_id
        })
        
        return jsonify({
            "message": "Payment failed, queued for manual review",
            "payout_id": payout_id
        }), 200
    
    # Payment succeeded!
    comment = f"""## 🎉 Payment Sent!

**Bounty Amount**: {amount:,} WATT
**Payout Wallet**: `{wallet}`
**Review Score**: {review_result.get('score', 'N/A')}/10
**TX Signature**: [{tx_signature[:8]}...{tx_signature[-8:]}](https://solscan.io/tx/{tx_signature})

Thank you for your contribution! 🚀
"""
    
    post_github_comment(pr_number, comment)
    
    log_security_event("auto_payment_success", {
        "pr_number": pr_number,
        "wallet": wallet,
        "amount": amount,
        "tx_signature": tx_signature,
        "bounty_issue_id": bounty_issue_id
    })
    
    return jsonify({
        "message": "Payment sent",
        "amount": amount,
        "wallet": wallet,
        "tx_signature": tx_signature
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


