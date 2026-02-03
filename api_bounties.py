"""
WattCoin Bounties API - Public endpoint for AI agents
GET /api/v1/bounties - List available bounties and agent tasks

Query params:
  - type: all (default), bounty, agent
  - tier: low, medium, high
  - status: open, claimed
  - min_amount: minimum WATT reward

No auth required. Cached for 5 minutes.
"""

import os
import re
import time
import requests
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

bounties_bp = Blueprint('bounties', __name__)

# Config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO = "WattCoin-Org/wattcoin"
STAKE_WALLET = "7vvNkG3JF3JpxLEavqZSkc5T3n9hHR98Uw23fbWdXVSF"
DOCS_URL = "https://github.com/WattCoin-Org/wattcoin/blob/main/CONTRIBUTING.md"
CACHE_TTL = 300  # 5 minutes

# Cache
_bounties_cache = {"data": None, "expires": 0}

def github_headers():
    """Get GitHub API headers."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

def parse_bounty_amount(title):
    """Extract bounty amount from issue title like '[BOUNTY: 100,000 WATT]'"""
    match = re.search(r'(\d{1,3}(?:,?\d{3})*)\s*WATT', title, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def get_tier(amount):
    """Determine tier based on amount."""
    if amount >= 100000:
        return "high"
    elif amount >= 20000:
        return "medium"
    return "low"

def parse_claimed_info(comments):
    """Parse claiming info from issue comments."""
    for comment in comments:
        body = (comment.get("body") or "").lower()
        if "claiming" in body or "i claim" in body:
            user = comment.get("user", {}).get("login", "")
            created_at = comment.get("created_at", "")
            
            # Look for wallet in comment
            wallet = None
            wallet_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', comment.get("body", ""))
            if wallet_match:
                wallet = wallet_match.group(0)
            
            return {
                "claimed_by": wallet,
                "claimed_by_github": user,
                "claimed_at": created_at
            }
    return None

def fetch_bounties():
    """Fetch bounties and agent tasks from GitHub API."""
    now = time.time()
    
    # Check cache
    if _bounties_cache["data"] and now < _bounties_cache["expires"]:
        return _bounties_cache["data"]
    
    bounties = []
    seen_ids = set()
    
    try:
        # Fetch issues with bounty OR agent-task labels (two calls, merge)
        labels_to_fetch = ["bounty", "agent-task"]
        all_issues = []
        
        for label in labels_to_fetch:
            url = f"https://api.github.com/repos/{REPO}/issues?labels={label}&state=open&per_page=100"
            resp = requests.get(url, headers=github_headers(), timeout=15)
            
            if resp.status_code == 200:
                all_issues.extend(resp.json())
        
        for issue in all_issues:
            # Skip PRs (they show up in issues endpoint)
            if issue.get("pull_request"):
                continue
            
            issue_number = issue.get("number")
            
            # Dedupe (in case issue has both labels)
            if issue_number in seen_ids:
                continue
            seen_ids.add(issue_number)
            title = issue.get("title", "")
            amount = parse_bounty_amount(title)
            
            if amount == 0:
                continue
            
            # Determine type from labels (agent-task takes priority)
            label_names = [l.get("name", "").lower() for l in issue.get("labels", [])]
            if "agent-task" in label_names:
                item_type = "agent"
            else:
                item_type = "bounty"
            
            # Clean title (remove bounty/agent-task tag)
            clean_title = re.sub(r'\[(BOUNTY|AGENT TASK)[:\s]*[\d,]+\s*WATT\]\s*', '', title, flags=re.IGNORECASE).strip()
            
            # Get issue body for description
            body = issue.get("body") or ""
            # Extract first paragraph as description
            description = ""
            if "## Description" in body:
                desc_match = re.search(r'## Description\s*\n+([^\n#]+)', body)
                if desc_match:
                    description = desc_match.group(1).strip()[:200]
            elif body:
                description = body.split('\n')[0][:200]
            
            # Check for claims in comments
            claimed_info = None
            status = "open"
            deadline = None
            
            # Fetch comments to check for claims
            comments_url = f"https://api.github.com/repos/{REPO}/issues/{issue_number}/comments"
            comments_resp = requests.get(comments_url, headers=github_headers(), timeout=10)
            if comments_resp.status_code == 200:
                comments = comments_resp.json()
                claimed_info = parse_claimed_info(comments)
                if claimed_info:
                    status = "claimed"
                    # Calculate deadline (7 days from claim)
                    if claimed_info.get("claimed_at"):
                        try:
                            claimed_dt = datetime.fromisoformat(claimed_info["claimed_at"].replace("Z", "+00:00"))
                            deadline_dt = claimed_dt + timedelta(days=7)
                            deadline = deadline_dt.isoformat().replace("+00:00", "Z")
                        except:
                            pass
            
            bounty = {
                "id": issue_number,
                "type": item_type,
                "title": clean_title,
                "amount": amount,
                "stake_required": int(amount * 0.1) if item_type == "bounty" else 0,
                "tier": get_tier(amount),
                "status": status,
                "url": issue.get("html_url"),
                "created_at": issue.get("created_at"),
                "description": description,
                "claimed_by": claimed_info.get("claimed_by") if claimed_info else None,
                "claimed_by_github": claimed_info.get("claimed_by_github") if claimed_info else None,
                "claimed_at": claimed_info.get("claimed_at") if claimed_info else None,
                "deadline": deadline
            }
            
            bounties.append(bounty)
        
        # Sort by amount descending
        bounties.sort(key=lambda x: x["amount"], reverse=True)
        
        # Update cache
        _bounties_cache["data"] = bounties
        _bounties_cache["expires"] = now + CACHE_TTL
        
    except Exception as e:
        print(f"Error fetching bounties: {e}")
    
    return bounties

@bounties_bp.route('/api/v1/bounties', methods=['GET'])
def list_bounties():
    """Public endpoint to list all bounties and agent tasks."""
    bounties = fetch_bounties()
    
    # Apply filters
    type_filter = request.args.get('type', 'all').lower()
    tier_filter = request.args.get('tier')
    status_filter = request.args.get('status')
    min_amount = request.args.get('min_amount', type=int)
    
    filtered = bounties
    
    # Type filter
    if type_filter == 'bounty':
        filtered = [b for b in filtered if b["type"] == "bounty"]
    elif type_filter == 'agent':
        filtered = [b for b in filtered if b["type"] == "agent"]
    # 'all' returns everything
    
    if tier_filter:
        filtered = [b for b in filtered if b["tier"] == tier_filter]
    
    if status_filter:
        filtered = [b for b in filtered if b["status"] == status_filter]
    
    if min_amount:
        filtered = [b for b in filtered if b["amount"] >= min_amount]
    
    # Calculate summary stats
    total_bounties = len([b for b in filtered if b["type"] == "bounty"])
    total_agent_tasks = len([b for b in filtered if b["type"] == "agent"])
    total_watt = sum(b["amount"] for b in filtered)
    
    return jsonify({
        "total": len(filtered),
        "total_bounties": total_bounties,
        "total_agent_tasks": total_agent_tasks,
        "total_watt": total_watt,
        "items": filtered,
        "stake_wallet": STAKE_WALLET,
        "docs": DOCS_URL,
        "cached_until": datetime.fromtimestamp(_bounties_cache["expires"]).isoformat() + "Z" if _bounties_cache["expires"] else None
    })
