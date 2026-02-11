# Agent Compute Services - Technical Specification

**Version:** 0.1.0 (Draft)  
**Status:** Parked (Design Complete)  
**Author:** Claude (Implementation Lead)  
**Reviewer:** Grok (Strategy Consultant)  

## References

- [WHITEPAPER.md](/WHITEPAPER.md) - Section: "Autonomous Digital Work", "AI Platforms"
- [docs/AI_VERIFICATION_SPEC.md](/docs/AI_VERIFICATION_SPEC.md) - Future verification integration
- [bridge.py](/bridge.py) - Existing Railway infrastructure

---

## 1. Overview

WATT-metered compute services for AI agents. Agents pay WATT for on-demand services (scraping, code execution, etc.) — creating real consumptive demand tied to utility.

### Why This Matters
- **Real Demand**: Agents need compute services daily
- **Zero API Cost**: We control the infrastructure (no per-call fees)
- **Profitable Day 1**: Any WATT charge > $0 is margin
- **Burns WATT**: 0.15% on every payment transaction
- **Whitepaper Fit**: "Autonomous Digital Work" + "Agent Economy Infrastructure"

### Why Not LLM Proxy (Yet)
At current WATT price (~$0.000004), LLM API costs (~$0.01/query) require 2,500+ WATT per query to break even. No incentive for agents vs paying USD directly. Revisit when MC > $100K or subsidize as premium tier later.

---

## 2. Service Roadmap

| Phase | Service | Effort | Status |
|-------|---------|--------|--------|
| v0.1 | **Web Scraper** | 3-5 days | Ready to build |
| v0.2 | **Code Sandbox** | 5-7 days | Planned |
| v0.3 | **File Storage** | 3-5 days | Planned |
| v1.0 | **LLM Proxy** | 2-3 days | When economics work |
| v2.0 | **Distributed Nodes** | Weeks | Future (users run nodes) |

---

## 3. Web Scraper Proxy (v0.1)

### What It Does
Agent sends URL + WATT → Service scrapes page → Returns clean data

### Why Agents Want This
- No rate limits (we rotate/manage)
- No CAPTCHAs (headless browser)
- Anonymous (agent's IP hidden)
- WATT-native (no credit card needed)
- Structured output (JSON option)

### Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      WEB SCRAPER FLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. PAYMENT                                                      │
│     └─→ Agent sends WATT to service wallet                      │
│     └─→ Includes job_id in memo                                 │
│                                                                  │
│  2. REQUEST                                                      │
│     └─→ POST /scrape                                            │
│     └─→ Body: { url, job_id, output_format }                    │
│                                                                  │
│  3. VERIFY                                                       │
│     └─→ Check payment received for job_id                       │
│     └─→ Verify amount >= required                               │
│                                                                  │
│  4. EXECUTE                                                      │
│     └─→ Scrape URL (requests or Playwright)                     │
│     └─→ Parse/clean content                                     │
│                                                                  │
│  5. RETURN                                                       │
│     └─→ Return data (text, JSON, or HTML)                       │
│     └─→ Include metadata (size, time, etc.)                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### API Specification

**Endpoint:** `POST /api/v1/scrape`

**Request:**
```json
{
  "url": "https://example.com/page",
  "job_id": "uuid-from-payment-memo",
  "output_format": "text|json|html",
  "selectors": {
    "title": "h1",
    "content": ".article-body"
  },
  "options": {
    "javascript": false,
    "screenshots": false,
    "timeout": 30
  }
}
```

**Response (Success):**
```json
{
  "success": true,
  "job_id": "uuid",
  "data": {
    "title": "Page Title",
    "content": "Extracted text content..."
  },
  "metadata": {
    "url": "https://example.com/page",
    "scraped_at": "ISO8601",
    "size_bytes": 4521,
    "execution_ms": 1234
  },
  "watt_charged": 200,
  "watt_burned": 0.3
}
```

**Response (Error):**
```json
{
  "success": false,
  "error": "Payment not found for job_id",
  "code": "PAYMENT_NOT_FOUND"
}
```

### Pricing

| Scrape Type | WATT Cost | Rationale |
|-------------|-----------|-----------|
| Simple (static HTML) | 100 WATT | Fast, low resource |
| Standard (with parsing) | 200 WATT | Default |
| JavaScript rendering | 500 WATT | Playwright, more compute |
| Screenshot included | 300 WATT | Additional output |

At $0.000004/WATT:
- 200 WATT = $0.0008 per scrape
- Pure profit (our cost: ~$0.0001 bandwidth)

### Technical Stack

| Component | Tool |
|-----------|------|
| Framework | Flask (extend bridge.py) |
| Simple scraping | requests + BeautifulSoup |
| JS rendering | Playwright (headless Chrome) |
| Hosting | Railway |
| Payment verification | Solana RPC |

### Rate Limits

| Limit | Value |
|-------|-------|
| Per agent | 100 scrapes/hour |
| Per URL | 10 scrapes/hour (prevent abuse) |
| Global | 10,000 scrapes/hour |

---

## 4. Code Sandbox (v0.2)

### What It Does
Agent sends code + WATT → Service executes in isolated container → Returns output

### Why Agents Want This
- Safe execution (sandboxed)
- No local setup required
- Multiple languages (Python, JS, Bash)
- WATT-native payment

### Flow

```
Agent sends: 500 WATT + code
           ↓
WattCoin verifies payment
           ↓
Spins up isolated Docker container
           ↓
Executes code (timeout: 30s)
           ↓
Returns: stdout, stderr, exit_code
```

### API Specification

**Endpoint:** `POST /api/v1/execute`

**Request:**
```json
{
  "job_id": "uuid-from-payment-memo",
  "language": "python|javascript|bash",
  "code": "print('Hello, WATT!')",
  "timeout": 30,
  "memory_mb": 256
}
```

**Response:**
```json
{
  "success": true,
  "job_id": "uuid",
  "output": {
    "stdout": "Hello, WATT!\n",
    "stderr": "",
    "exit_code": 0
  },
  "metadata": {
    "language": "python",
    "execution_ms": 45,
    "memory_used_mb": 12
  },
  "watt_charged": 500
}
```

### Pricing

| Execution Type | WATT Cost |
|----------------|-----------|
| Quick (< 5s, < 128MB) | 300 WATT |
| Standard (< 30s, < 256MB) | 500 WATT |
| Extended (< 60s, < 512MB) | 1000 WATT |

### Security

| Risk | Mitigation |
|------|------------|
| Malicious code | Isolated Docker, no network |
| Resource abuse | CPU/memory limits, timeout |
| Escape attempts | Unprivileged container, seccomp |
| Infinite loops | Hard timeout (kill after limit) |

### Technical Stack

| Component | Tool |
|-----------|------|
| Container | Docker with resource limits |
| Languages | Python 3.11, Node 20, Bash |
| Isolation | No network, read-only filesystem |
| Hosting | Railway (or dedicated VM for security) |

---

## 5. Payment Architecture

### Wallet

| Wallet | Purpose |
|--------|---------|
| **Compute Services Wallet** | Receives payments for scrape/execute jobs |

Create new dedicated wallet before launch.

### Payment Flow

```
1. Agent generates job_id (UUID)
2. Agent sends WATT to compute wallet with job_id in memo
3. Agent calls API with job_id
4. Service checks RPC for payment with matching job_id
5. If verified: execute job
6. If not found: return error
```

### Verification Code

```python
from solana.rpc.api import Client

def verify_payment(job_id: str, min_amount: int) -> bool:
    client = Client("https://api.mainnet-beta.solana.com")
    
    # Get recent transactions to compute wallet
    txs = client.get_signatures_for_address(COMPUTE_WALLET)
    
    for tx in txs:
        # Check memo for job_id
        # Verify amount >= min_amount
        # Return True if match
        pass
    
    return False
```

### Alternative: Pre-Pay Balance (v0.2)

Instead of per-job payments:
- Agent deposits WATT to balance
- Service deducts per job
- Faster (no per-job TX)
- Track in database

---

## 6. Infrastructure

### Railway Deployment

Extend existing `bridge.py` or create new service:

```
your-backend-url.example.com
├── /health              (existing)
├── /proxy               (existing)
├── /api/v1/scrape       (new)
├── /api/v1/execute      (new)
└── /api/v1/balance      (new - check prepaid balance)
```

### Environment Variables

```
COMPUTE_WALLET=<new_wallet_address>
COMPUTE_WALLET_PRIVATE_KEY=<for_refunds_only>
SCRAPE_PRICE_SIMPLE=100
SCRAPE_PRICE_STANDARD=200
SCRAPE_PRICE_JS=500
EXECUTE_PRICE_QUICK=300
EXECUTE_PRICE_STANDARD=500
```

### Dependencies

```
# requirements.txt additions
beautifulsoup4>=4.12.0
playwright>=1.40.0
docker>=7.0.0  # for sandbox
```

---

## 7. Anti-Abuse

| Risk | Mitigation |
|------|------------|
| Scraping abuse (DDoS via proxy) | Rate limits, banned domains list |
| Payment spam | Minimum payment threshold |
| Resource exhaustion | Per-agent limits, global caps |
| Illegal content scraping | Blocked domains (illegal sites) |
| Code sandbox escape | Hardened Docker, no network |

### Blocked Domains (Scraper)

```python
BLOCKED_DOMAINS = [
    "localhost",
    "127.0.0.1",
    "*.gov",  # be careful
    # Add illegal/sensitive sites
]
```

---

## 8. Metrics & Monitoring

| Metric | Track |
|--------|-------|
| Total scrapes | Count |
| Total executions | Count |
| WATT received | Sum |
| WATT burned | Sum |
| Unique agents | Count |
| Avg response time | ms |
| Error rate | % |
| Most scraped domains | List |

---

## 9. Launch Plan

### Phase 1: Web Scraper (v0.1)
- [ ] Create compute services wallet
- [ ] Build `/api/v1/scrape` endpoint
- [ ] Payment verification logic
- [ ] Rate limiting
- [ ] Deploy to Railway
- [ ] Test with real agents
- [ ] Announce on X/Moltbook

### Phase 2: Code Sandbox (v0.2)
- [ ] Docker sandbox setup
- [ ] Build `/api/v1/execute` endpoint
- [ ] Security hardening
- [ ] Deploy and test
- [ ] Announce

### Phase 3: Enhancements
- [ ] Pre-pay balance system
- [ ] Usage dashboard
- [ ] Bulk pricing discounts
- [ ] Rotating proxies (scraper)
- [ ] More languages (sandbox)

---

## 10. Success Metrics

| Metric | Target (30 days) |
|--------|------------------|
| Total jobs executed | 1,000+ |
| Unique agents | 50+ |
| WATT received | 500K+ |
| Uptime | 99%+ |
| Avg response time | < 5s (scraper), < 10s (sandbox) |

---

## 11. Future: LLM Proxy (When Economics Work)

When WATT MC > $100K (price ~$0.0001):
- 2,500 WATT = $0.25 (can absorb $0.01 API cost)
- Add as premium tier
- Or subsidize from ecosystem pool as loss-leader

**Pricing (future):**
| Model | WATT per 1K tokens |
|-------|-------------------|
| Grok | 500 input / 1000 output |
| Claude | 500 input / 1000 output |
| GPT-4o | 500 input / 1000 output |

---

## 12. Future: Distributed Compute (v2.0)

Users run nodes, earn WATT for providing compute:

```
┌─────────────┐                    ┌─────────────┐
│   AGENT     │ ──── Job + WATT ──→│   ROUTER    │
└─────────────┘                    └──────┬──────┘
                                          │
                   ┌──────────────────────┼──────────────────────┐
                   ▼                      ▼                      ▼
            ┌───────────┐          ┌───────────┐          ┌───────────┐
            │  NODE 1   │          │  NODE 2   │          │  NODE 3   │
            │  (Pi)     │          │  (PC)     │          │  (GPU)    │
            │  earns    │          │  earns    │          │  earns    │
            │  WATT     │          │  WATT     │          │  WATT     │
            └───────────┘          └───────────┘          └───────────┘
```

This is the full decentralized vision — park for post-PMF.

---

## 13. Appendix

### A. Sample Announcement

```
⚡ WATT Compute Services v0.1 — Web Scraper LIVE

Agents: Pay WATT for reliable web scraping.

✅ No rate limits
✅ No CAPTCHAs  
✅ Anonymous
✅ Structured JSON output

Pricing: 100-500 WATT per scrape (~$0.0004-0.002)

API: https://your-backend-url.example.com/api/v1/scrape
Docs: [link]

Real utility. Real demand. Real burn.

$WATT | Powering the agent economy 🤖
```

### B. Error Codes

| Code | Description |
|------|-------------|
| PAYMENT_NOT_FOUND | No payment found for job_id |
| PAYMENT_INSUFFICIENT | Payment below required amount |
| RATE_LIMITED | Too many requests |
| DOMAIN_BLOCKED | URL domain not allowed |
| SCRAPE_FAILED | Could not fetch URL |
| EXECUTION_TIMEOUT | Code exceeded time limit |
| EXECUTION_ERROR | Code threw exception |

### C. Example Agent Integration

```python
# Agent code to use WATT scraper
import requests
from solana.rpc.api import Client
import uuid

# 1. Generate job ID
job_id = str(uuid.uuid4())

# 2. Send payment (200 WATT) with job_id in memo
# ... solana transaction code ...

# 3. Call scraper API
response = requests.post(
    "https://your-backend-url.example.com/api/v1/scrape",
    json={
        "url": "https://news.site/article",
        "job_id": job_id,
        "output_format": "json",
        "selectors": {"title": "h1", "body": "article"}
    }
)

data = response.json()
print(data["data"]["title"])
```
