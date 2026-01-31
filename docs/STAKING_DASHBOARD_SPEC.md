# No-Code Staking Dashboard - Technical Specification

**Version:** 0.1.0 (Draft)  
**Status:** Parked (Design Complete)  
**Author:** Claude (Implementation Lead)  
**Reviewer:** Grok (Strategy Consultant)  

## References

- [WHITEPAPER.md](/WHITEPAPER.md) - Section: "Energy Rewards", "Task Marketplace", "Owner Benefits"
- [docs/AI_VERIFICATION_SPEC.md](/docs/AI_VERIFICATION_SPEC.md) - Future integration for auto-verification
- [tipping/](/tipping/) - Similar manual payout pattern

---

## 1. Overview

A no-code web dashboard (Bubble.io) where WATT holders stake tokens to earn priority task access and participation-based rebates. Manual verification v1, on-chain escrow v2.

### Core Value Proposition
- **For Holders**: Stake WATT → complete tasks → earn rebates
- **For Project**: Proves utility, locks supply, bootstraps ecosystem pool usage
- **Regulatory**: No yields, no passive income — rebates tied to verified participation only

---

## 2. Locked Design Decisions

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Escrow wallet | New dedicated wallet | Clean separation from tips |
| Minimum stake | 1,000 WATT (~$4) | Low barrier, filters dust |
| Lock period | Flexible, 7-day unstake delay | Encourages commitment without scaring early holders |
| Rebate model | 500-2000 WATT per verified action | Participation-based, not passive yield |
| Claim frequency | 1 per week max per user | Prevents spam, encourages quality |
| Verification | Manual review v1 | Fast launch, iterate to auto later |
| Tool | Bubble.io | No-code, 2-4 day build |

---

## 3. User Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         STAKING FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. CONNECT                                                      │
│     └─→ User connects Phantom wallet                            │
│                                                                  │
│  2. STAKE                                                        │
│     └─→ Input amount (min 1,000 WATT)                           │
│     └─→ Send to escrow wallet (standard SPL transfer)           │
│     └─→ Submit TX signature on dashboard                        │
│     └─→ Admin verifies → status = "Staked"                      │
│                                                                  │
│  3. PARTICIPATE                                                  │
│     └─→ Complete qualifying action (Pi Logger, bounty, etc.)    │
│     └─→ Submit proof via claim form                             │
│                                                                  │
│  4. CLAIM REBATE                                                 │
│     └─→ Admin reviews proof (1-2 days)                          │
│     └─→ Approved → rebate sent from ecosystem pool              │
│     └─→ 1 claim per week max                                    │
│                                                                  │
│  5. UNSTAKE                                                      │
│     └─→ Request unstake via dashboard                           │
│     └─→ 7-day delay                                             │
│     └─→ Admin returns WATT to user wallet                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. What Counts as "Verified Participation"

### Qualifying Actions (v0.1)

| Action | Proof Required | Rebate Tier |
|--------|----------------|-------------|
| Ran Pi Logger script | Screenshot + energy log | 500-1000 WATT |
| Completed task bounty | Deliverable + bounty ID | 500-2000 WATT |
| Efficiency demonstration | kWh data for task completion | 1000-2000 WATT |
| Beta testing new feature | Feedback form + screenshots | 500 WATT |

### NOT Qualifying
- Passive staking (just holding)
- Time-based rewards
- Referrals without action

### Rebate Scaling by Stake Size

| Stake Amount | Rebate Multiplier |
|--------------|-------------------|
| 1,000 - 9,999 WATT | 1x (base) |
| 10,000 - 49,999 WATT | 1.5x |
| 50,000+ WATT | 2x |

Example: Base rebate 500 WATT × 2x multiplier = 1000 WATT for 50K+ stakers.

---

## 5. Priority Benefits

Stakers receive:

| Benefit | Description |
|---------|-------------|
| **Early bounty access** | Tagged/notified before public announcement |
| **Higher rebate tier** | Multiplier based on stake size |
| **Priority Staker badge** | Visible on dashboard profile |
| **Future**: Governance input | Feedback on feature priorities (advisory, not voting) |

---

## 6. Wallet Architecture

### Wallets

| Wallet | Purpose | Address |
|--------|---------|---------|
| Tip Wallet | Moltbook/X tipping | `7tYQQX8Uhx86oKPQLNwuYnqmGmdkm2hSSkx3N2KDWqYL` |
| Staking Escrow | Holds staked WATT | TBD (create before launch) |
| Ecosystem Pool | Rebate payouts | Main dev wallet or dedicated |

### Funding
- Transfer 10-20M WATT to escrow wallet for rebate pool
- Replenish from ecosystem allocation (40% of supply) as needed

---

## 7. Bubble.io Implementation

### Pages

| Page | Components |
|------|------------|
| **Landing** | Hero, total staked counter, CA/whitepaper links, "Connect Wallet" CTA |
| **Stake** | Amount input, escrow address display, TX signature input, submit button |
| **Dashboard** | User's staked amount, lock timer, claim form, rebate history |
| **Admin** | All stakers list, pending claims, approve/reject buttons, payout tracker |

### Database Schema

**Users**
```
- wallet_address (text, unique)
- staked_amount (number)
- stake_tx_sig (text)
- stake_verified (boolean)
- staked_at (datetime)
- unstake_requested (datetime, nullable)
- total_rebates_earned (number)
- last_claim_date (datetime)
```

**Claims**
```
- user_wallet (text)
- action_type (text: pi_logger, bounty, efficiency, beta)
- proof_link (text)
- proof_description (text)
- amount_requested (number)
- status (text: pending, approved, rejected)
- submitted_at (datetime)
- reviewed_at (datetime)
- rebate_tx_sig (text, nullable)
```

**Unstake_Requests**
```
- user_wallet (text)
- amount (number)
- requested_at (datetime)
- eligible_at (datetime) // +7 days
- processed (boolean)
- return_tx_sig (text, nullable)
```

### Plugins Required
- Phantom Wallet Connect (or generic Solana wallet adapter)
- Optional: Solana RPC for balance checks

---

## 8. Verification Process

### v0.1: Manual

1. User submits TX signature
2. Admin checks Solscan: https://solscan.io/tx/{signature}
3. Verify: correct amount, correct destination (escrow), confirmed
4. Update Bubble DB → user sees "Staked" status

### v0.2: Semi-Auto

```python
# Simple verification script (Railway or local)
from solana.rpc.api import Client

def verify_stake(tx_sig, escrow_wallet, expected_amount):
    client = Client("https://api.mainnet-beta.solana.com")
    tx = client.get_transaction(tx_sig)
    # Parse for SPL transfer to escrow_wallet
    # Return True if valid, False otherwise
```

### v1.0: Full On-Chain
- Integrate with repo's existing staking contract
- Auto-stake/unstake via smart contract
- AI verification for task proofs

---

## 9. Anti-Abuse Measures

| Risk | Mitigation |
|------|------------|
| Fake proof submissions | Manual review, require specific evidence |
| Claim spam | 1 claim per week limit |
| Stake/unstake gaming | 7-day unstake delay |
| Sybil attacks (multiple wallets) | Manual review catches patterns |
| Dust stakes | 1,000 WATT minimum |

---

## 10. Launch Plan

### Pre-Launch
- [ ] Create dedicated escrow wallet
- [ ] Fund escrow with 10-20M WATT
- [ ] Build Bubble.io dashboard (2-4 days)
- [ ] Test with team wallets
- [ ] Write user guide

### Launch
- [ ] Announce on X: "WATT Staking Dashboard v0.1 live"
- [ ] Post on Moltbook (when API works)
- [ ] First 10 stakers get bonus rebate

### Post-Launch
- [ ] Monitor claims, adjust rebate amounts
- [ ] Gather feedback
- [ ] Plan v0.2 (semi-auto verification)

---

## 11. Success Metrics

| Metric | Target (30 days) |
|--------|------------------|
| Unique stakers | 50+ |
| Total WATT staked | 5M+ |
| Claims submitted | 100+ |
| Claims approved | 80%+ |
| Rebates distributed | 500K WATT |

---

## 12. Future Enhancements (v0.2+)

- [ ] Semi-auto TX verification via Solana RPC
- [ ] Tiered lock periods (7/30/90 days = higher multipliers)
- [ ] Integration with Pi Logger (auto-submit proofs)
- [ ] Integration with Task Bounty Board
- [ ] On-chain escrow contract (from repo)
- [ ] AI verification for proof validation
- [ ] Leaderboard for top stakers
- [ ] Discord role sync for stakers

---

## 13. Regulatory Notes

**This is NOT a yield product:**
- No guaranteed returns
- No passive income
- Rebates are discretionary, participation-based
- Tied to verifiable utility actions
- Language: "rebates" and "priority access", never "APY" or "interest"

---

## 14. Appendix

### A. Claim Form Fields

1. Wallet address (auto-filled from connection)
2. Action type (dropdown: Pi Logger, Bounty, Efficiency, Beta Test, Other)
3. Proof link (URL to screenshot, TX, or deliverable)
4. Description (text: what you did, 1-3 sentences)
5. Submit button

### B. Sample Announcement

```
⚡ WATT Staking Dashboard v0.1 is LIVE

Stake WATT → Complete tasks → Earn rebates

✅ Priority access to bounties
✅ Rebate multiplier (up to 2x)
✅ No lockup (7-day unstake delay)

Min stake: 1,000 WATT
Rebates: 500-2000 WATT per verified action

Dashboard: [bubble link]
Escrow wallet: [address]

Utility, not yield. Participation, not passive.

$WATT | Powering the machine economy 🤖
```
