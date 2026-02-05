# GitHub Webhook Setup Guide

## Overview
The WattCoin automation system uses GitHub webhooks to trigger automatic PR review, merge, and payment. This guide shows how to configure the webhook in your repository.

## What Gets Automated

### Full Flow:
```
PR opened → Grok auto-reviews → Score ≥85% → Auto-merge → Auto-payment → Railway deploys
```

### Specific Actions:
1. **PR Opened/Updated** → Triggers Grok code review automatically
2. **High Score (≥85%)** → Auto-merges PR without manual approval
3. **PR Merged** → Executes payment via `bounty_auto_pay.py` automatically
4. **Payment Confirmed** → Posts TX signature to PR comments

## Prerequisites

### Required Environment Variables (Railway):
```bash
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
GITHUB_TOKEN=ghp_YOUR_GITHUB_TOKEN_HERE
GROK_API_KEY=xai-YOUR_GROK_API_KEY_HERE
BOUNTY_WALLET_PRIVATE_KEY=your_private_key_here
BASE_URL=https://wattcoin-production-81a7.up.railway.app
```

## GitHub Webhook Configuration

### Step 1: Create Webhook Secret
```bash
# Generate a secure random secret
openssl rand -hex 32
# Example output: a1b2c3d4e5f6...
```

### Step 2: Add Secret to Railway
1. Go to Railway dashboard → wattcoin project
2. Navigate to Variables tab
3. Add: `GITHUB_WEBHOOK_SECRET` = `<your_generated_secret>`

### Step 3: Configure GitHub Webhook
1. Go to: https://github.com/WattCoin-Org/wattcoin/settings/hooks
2. Click "Add webhook"
3. Configure:
   - **Payload URL**: `https://wattcoin-production-81a7.up.railway.app/webhooks/github`
   - **Content type**: `application/json`
   - **Secret**: `<your_generated_secret>` (same as Railway)
   - **Which events**: Select "Let me select individual events"
     - ✅ Pull requests
     - ✅ Pull request reviews (optional)
   - **Active**: ✅ Checked
4. Click "Add webhook"

### Step 4: Test Webhook
```bash
# Check webhook health
curl https://wattcoin-production-81a7.up.railway.app/webhooks/health
# Expected: {"status":"ok","webhook_secret_configured":true}
```

## How It Works

### Event: PR Opened
1. Webhook receives `pull_request` event with action `opened`
2. Calls `/api/v1/review_pr` internally to trigger Grok review
3. Grok analyzes code diff and assigns score 0-100
4. Posts review comment on PR with score and findings
5. If score ≥85%, attempts auto-merge
6. If auto-merge succeeds, waits for merge event to trigger payment

### Event: PR Synchronized (Updated)
1. When PR is updated with new commits
2. Re-triggers Grok review automatically
3. Updates review comment with new score
4. Auto-merge attempt if new score ≥85%

### Event: PR Merged
1. Webhook receives `pull_request` event with action `closed` and `merged=true`
2. Validates PR has review record (from earlier auto-review)
3. Extracts wallet address from PR body
4. Extracts bounty amount from referenced issue
5. Calls `bounty_auto_pay.py <pr_number>` directly
6. Posts TX signature to PR comments
7. If payment fails, queues for manual approval

## Merge Threshold

**Current Setting:** Score ≥ 85% required for auto-merge

To change threshold, edit `api_webhooks.py`:
```python
MERGE_THRESHOLD = 85  # Change this value
```

## Security Features

1. **Signature Verification**: All webhooks verified using HMAC-SHA256
2. **Emergency Pause**: Can disable payouts via `pr_security.py`
3. **Dangerous Code Scanner**: Blocks malicious code patterns
4. **Rate Limiting**: Prevents spam submissions
5. **Fallback Queue**: Failed auto-payments queue for manual review

## Path-Based Deploy Rules

Railway only deploys when these files change:
- `api_*.py` (backend APIs)
- `bridge_web.py` (main server)
- `requirements.txt` (dependencies)
- `railway.toml` (config)

**Safe to merge without redeploy:**
- Documentation (`*.md`, `docs/**`)
- Tests (`tests/**`)
- Client code (`wattnode/**`, `tipping/**`)
- Bounty tracking files (`bounty/**`)

## Manual Override

If you need to disable automation temporarily:

**Disable Auto-Review:**
```python
# In api_webhooks.py, comment out:
# if action in ["opened", "synchronize"]:
#     return handle_pr_review_trigger(pr_number, action)
```

**Disable Auto-Merge:**
```python
# In api_webhooks.py, set:
MERGE_THRESHOLD = 101  # Impossible to reach
```

**Disable Auto-Payment:**
```python
# In api_webhooks.py, replace execute_auto_payment() call with:
# payout_id = queue_payout(pr_number, wallet, amount, bounty_issue_id, review_data)
```

## Monitoring

### Check Recent Webhooks:
https://github.com/WattCoin-Org/wattcoin/settings/hooks

### Check Security Logs:
```python
# On Railway container
cat /app/data/security_logs.json | tail -20
```

### Check Auto-Payments:
```python
# View payment history
cat /app/data/bounty_reviews.json
```

## Troubleshooting

### Webhook Not Firing
- Check webhook is "Active" in GitHub settings
- Verify payload URL is correct
- Check Railway logs for incoming requests

### Auto-Review Fails
- Verify `GROK_API_KEY` is set in Railway
- Check Grok API rate limits
- Review logs: `railway logs --tail 100`

### Auto-Merge Fails
- Check GitHub token has write permissions
- Verify PR has no merge conflicts
- Check branch protection rules

### Auto-Payment Fails
- Verify `BOUNTY_WALLET_PRIVATE_KEY` is set
- Check wallet has sufficient WATT balance
- Verify Solana RPC is responsive

## Testing the Full Flow

1. **Create test PR with bounty:**
   ```markdown
   Fixes #123
   
   **Payout Wallet**: 7tYQQX8Uhx86oKPQLNwuYnqmGmdkm2hSSkx3N2KDWqYL
   ```

2. **Watch for auto-review comment** (within 30 seconds)

3. **If score ≥85%, PR auto-merges**

4. **Watch for payment comment** with TX signature

5. **Verify on Solscan**: https://solscan.io/tx/<signature>

## Support

If automation fails, payouts are queued for manual review at:
https://wattcoin-production-81a7.up.railway.app/admin/dashboard

Admin can approve queued payouts with one click.
