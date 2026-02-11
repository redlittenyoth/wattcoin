#!/usr/bin/env python3
"""
Grok Bounty PR Review Script
Fetches PR diff from GitHub and sends to Grok for review.

Usage:
    python grok_pr_review.py <pr_number>
    python grok_pr_review.py 7

Environment variables:
    GROK_API_KEY - Your Grok API key (required)
    GITHUB_TOKEN - GitHub token for private repos (optional for public)
"""

import os
import requests
import sys
import json

# Configuration
GROK_API_KEY = os.getenv("GROK_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROK_API_URL = os.getenv("AI_API_BASE_URL", "") + "/chat/completions"
REPO = "WattCoin-Org/wattcoin"

def get_pr_info(pr_number: int) -> dict:
    """Fetch PR details from GitHub."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    # Get PR info
    pr_url = f"https://api.github.com/repos/{REPO}/pulls/{pr_number}"
    pr_response = requests.get(pr_url, headers=headers)
    
    if pr_response.status_code != 200:
        raise Exception(f"Failed to fetch PR: {pr_response.status_code}")
    
    pr_data = pr_response.json()
    
    # Get PR diff
    diff_headers = headers.copy()
    diff_headers["Accept"] = "application/vnd.github.v3.diff"
    diff_response = requests.get(pr_url, headers=diff_headers)
    
    if diff_response.status_code != 200:
        raise Exception(f"Failed to fetch diff: {diff_response.status_code}")
    
    return {
        "number": pr_number,
        "title": pr_data.get("title", "Unknown"),
        "author": pr_data.get("user", {}).get("login", "Unknown"),
        "body": pr_data.get("body", "No description"),
        "diff": diff_response.text[:15000],  # Limit diff size for API
        "url": pr_data.get("html_url", ""),
        "linked_issues": extract_issue_numbers(pr_data.get("body", ""))
    }

def extract_issue_numbers(body: str) -> list:
    """Extract issue numbers from PR body (e.g., 'Closes #3')."""
    import re
    pattern = r'(?:closes|fixes|resolves)\s*#(\d+)'
    matches = re.findall(pattern, body.lower())
    return matches

def get_issue_info(issue_number: int) -> dict:
    """Fetch issue details from GitHub."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    url = f"https://api.github.com/repos/{REPO}/issues/{issue_number}"
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return {"title": "Unknown", "body": "Could not fetch issue"}
    
    data = response.json()
    return {
        "title": data.get("title", "Unknown"),
        "body": data.get("body", "No description")
    }

def review_pr(pr_info: dict, issue_info: dict = None) -> str:
    """Send PR to Grok for review."""
    
    if not GROK_API_KEY:
        return "Error: GROK_API_KEY environment variable not set"
    
    issue_context = ""
    if issue_info:
        issue_context = f"""
BOUNTY ISSUE:
Title: {issue_info['title']}
Description: {issue_info['body'][:2000]}
"""
    
    prompt = f"""You are a strict bounty reviewer for WattCoin agent-native OSS.
Review this Pull Request for a bounty task.

{issue_context}

PR #{pr_info['number']}: {pr_info['title']}
Author: {pr_info['author']}
Description: {pr_info['body'][:1000]}

DIFF:
```
{pr_info['diff']}
```

Check:
1. Does it solve the bounty issue fully?
2. Code quality (clean, readable, follows existing patterns)?
3. Security (no backdoors, hardcoded secrets, suspicious patterns)?
4. Tests (added/updated if applicable)?
5. Completeness (% done, what's missing)?

Output in this exact format:

🤖 GROK BOUNTY REVIEW

**Issue:** #{pr_info.get('linked_issues', ['?'])[0] if pr_info.get('linked_issues') else '?'} - {issue_info['title'] if issue_info else 'Unknown'}
**PR:** #{pr_info['number']} by {pr_info['author']}

| Check | Status | Notes |
|-------|--------|-------|
| Solves issue | ✅/⚠️/❌ | explanation |
| Code quality | ✅/⚠️/❌ | explanation |
| Security | ✅/⚠️/❌ | explanation |
| Tests | ✅/⚠️/❌ | explanation |
| Completeness | X% | what's missing |

**RECOMMENDATION:** Approve / Request changes / Reject
**REASON:** Brief explanation
**SUGGESTED PAYOUT:** 100% / X% / 0%
"""

    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": os.getenv("AI_REVIEW_MODEL", ""),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1500
    }
    
    response = requests.post(GROK_API_URL, headers=headers, json=data)
    
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        return f"Error: {response.status_code} - {response.text}"

def main():
    if len(sys.argv) < 2:
        print("Usage: python grok_pr_review.py <pr_number>")
        print("Example: python grok_pr_review.py 7")
        print("\nSet GROK_API_KEY environment variable before running.")
        sys.exit(1)
    
    pr_number = int(sys.argv[1])
    
    print(f"Fetching PR #{pr_number}...")
    pr_info = get_pr_info(pr_number)
    
    print(f"PR: {pr_info['title']} by {pr_info['author']}")
    print(f"URL: {pr_info['url']}")
    
    # Get linked issue if any
    issue_info = None
    if pr_info['linked_issues']:
        issue_num = int(pr_info['linked_issues'][0])
        print(f"Linked to issue #{issue_num}, fetching...")
        issue_info = get_issue_info(issue_num)
    
    print("\nSending to Grok for review...\n")
    print("=" * 60)
    
    review = review_pr(pr_info, issue_info)
    print(review)
    
    print("=" * 60)
    print("\n⚠️  This is an AI assessment. Final decision is yours.")

if __name__ == "__main__":
    main()
