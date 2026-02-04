# PR Bounty Loop - Integration Instructions

## Files Created (Session 1)

1. **pr_security.py** - Security utilities module
   - Wallet validation
   - Rate limiting (5 PRs/day + 24h cooldown)
   - Code scanning (dangerous patterns)
   - Security logging
   - Emergency pause controls

2. **api_pr_review.py** - PR Review endpoint
   - POST /api/v1/review_pr
   - Calls Grok API for code review
   - Posts review comments on GitHub
   - Validates PR format
   - Records reviews to data/pr_reviews.json

3. **api_webhooks.py** - GitHub webhook handler
   - POST /webhooks/github
   - Listens for merged PRs
   - Queues payouts (manual approval required)
   - Posts status comments
   - Tracks payouts in data/pr_payouts.json

4. **Data Files** (in /data/)
   - pr_reviews.json - Review history
   - pr_payouts.json - Payout queue
   - pr_rate_limits.json - Rate limit tracking
   - security_logs.json - Security events

## Integration Steps

### Step 1: Add Files to Repository

Copy these files to the WattCoin-Org/wattcoin repo:
```
/pr_security.py
/api_pr_review.py
/api_webhooks.py
/data/pr_reviews.json
/data/pr_payouts.json
/data/pr_rate_limits.json
/data/security_logs.json
```

### Step 2: Update bridge_web.py

Add these imports near the top (around line 60, after existing blueprint imports):

```python
from api_pr_review import pr_review_bp
from api_webhooks import webhooks_bp
```

Add these blueprint registrations (around line 67, after existing registrations):

```python
app.register_blueprint(pr_review_bp)
app.register_blueprint(webhooks_bp)
```

### Step 3: Update requirements.txt

Add (if not already present):
```
base58>=2.1.1
```

### Step 4: Set Environment Variables (Railway)

Add these to Railway environment:
```
GITHUB_WEBHOOK_SECRET=<generate_random_secret>
PAUSE_PR_PAYOUTS=false
PAUSE_PR_REVIEWS=false
REQUIRE_DOUBLE_APPROVAL=false
```

To generate webhook secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 5: Configure GitHub Webhook

1. Go to: https://github.com/WattCoin-Org/wattcoin/settings/hooks
2. Click "Add webhook"
3. Set Payload URL: `https://wattcoin-production-81a7.up.railway.app/webhooks/github`
4. Set Content type: `application/json`
5. Set Secret: (use same as GITHUB_WEBHOOK_SECRET env var)
6. Select events: "Let me select individual events"
   - Check: "Pull requests"
7. Ensure "Active" is checked
8. Click "Add webhook"

### Step 6: Test Health Endpoints

After deployment:
```bash
# Test webhook health
curl https://wattcoin-production-81a7.up.railway.app/webhooks/health

# Should return:
# {"status": "ok", "webhook_secret_configured": true}
```

## API Endpoints

### POST /api/v1/review_pr
Submit a PR for Grok review.

**Request:**
```json
{
  "pr_url": "https://github.com/WattCoin-Org/wattcoin/pull/123",
  "bounty_issue_id": 45
}
```

**Response:**
```json
{
  "success": true,
  "review": {
    "pass": true,
    "score": 9,
    "feedback": "Excellent contribution...",
    "suggested_changes": ["..."],
    "concerns": []
  },
  "security": {
    "is_safe": true,
    "warnings": []
  },
  "pr_number": 123,
  "wallet": "7vvNkG...",
  "remaining_prs": 4,
  "comment_posted": true
}
```

### POST /webhooks/github
GitHub webhook receiver (called automatically by GitHub).

Handles:
- PR merge events
- Validates review passed
- Extracts wallet & bounty amount
- Queues payout for manual approval

## Security Features

1. **Rate Limiting**
   - 5 PRs per wallet per 24 hours
   - 24h cooldown after successful payout

2. **Code Scanning**
   - Blocks dangerous patterns: subprocess, os.system, eval, etc.
   - Flags in review but doesn't auto-reject

3. **Emergency Controls**
   - PAUSE_PR_PAYOUTS - stops all payouts
   - PAUSE_PR_REVIEWS - stops new reviews
   - REQUIRE_DOUBLE_APPROVAL - requires 2 admins

4. **Wallet Validation**
   - Requires exact format in PR body
   - Base58 validation
   - Length checks

5. **Logging**
   - All security events logged to data/security_logs.json
   - Blocked PRs, rate limits, dangerous code

## Data Storage

All data stored in JSON files under `/data/`:

- **pr_reviews.json** - Complete review history with scores
- **pr_payouts.json** - Payout queue with approval status
- **pr_rate_limits.json** - Per-wallet submission tracking
- **security_logs.json** - Security events (last 1000)

## Next Steps (Session 2)

1. Build admin dashboard UI for payout approval
2. Add payout execution from dashboard
3. Add PR/review viewing in admin panel
4. Enhanced code scanning patterns
5. Testing with dummy PRs

## Testing Checklist

- [ ] Deploy to Railway
- [ ] Configure GitHub webhook
- [ ] Test /webhooks/health endpoint
- [ ] Create test PR with wallet in body
- [ ] Call /api/v1/review_pr endpoint
- [ ] Verify Grok comment posted
- [ ] Merge test PR
- [ ] Verify webhook triggered
- [ ] Check payout queued in data/pr_payouts.json
- [ ] Test rate limiting (submit 6 PRs)
- [ ] Test emergency pause env vars

## Emergency Procedures

**To pause all activity:**
```bash
# In Railway, set:
PAUSE_PR_REVIEWS=true
PAUSE_PR_PAYOUTS=true
```

**To clear rate limits for a wallet:**
Edit `data/pr_rate_limits.json` and remove the wallet entry.

**To view security logs:**
```bash
cat data/security_logs.json | jq '.events[-10:]'
```
