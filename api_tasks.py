"""
WattCoin Agent Tasks API - Task discovery for AI agents
GET /api/v1/tasks - List all agent tasks (label: agent-task)
"""

import os
import re
import requests
from flask import Blueprint, jsonify, request
from datetime import datetime

tasks_bp = Blueprint('tasks', __name__)

# Config
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = "WattCoin-Org/wattcoin"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/issues"

# Cache
_tasks_cache = {"data": None, "expires": 0}
CACHE_TTL = 300  # 5 minutes

# =============================================================================
# HELPERS
# =============================================================================

def parse_task_amount(title):
    """Extract WATT amount from title like [AGENT TASK: 1,000 WATT]"""
    match = re.search(r'\[AGENT\s*TASK:\s*([\d,]+)\s*WATT\]', title, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

def get_task_type(body):
    """Determine if task is recurring or one-time based on body content."""
    if not body:
        return "one-time"
    body_lower = body.lower()
    if any(word in body_lower for word in ['daily', 'weekly', 'monthly', 'recurring', 'every day', 'every week']):
        return "recurring"
    return "one-time"

def get_frequency(body):
    """Extract frequency from body for recurring tasks."""
    if not body:
        return None
    body_lower = body.lower()
    if 'daily' in body_lower or 'every day' in body_lower:
        return "daily"
    if 'weekly' in body_lower or 'every week' in body_lower:
        return "weekly"
    if 'monthly' in body_lower or 'every month' in body_lower:
        return "monthly"
    return None

def clean_title(title):
    """Remove [AGENT TASK: X WATT] prefix from title."""
    return re.sub(r'\[AGENT\s*TASK:\s*[\d,]+\s*WATT\]\s*', '', title, flags=re.IGNORECASE).strip()

def extract_section(body, header):
    """Extract content under a markdown header."""
    if not body:
        return None
    pattern = rf'#+\s*{header}\s*\n(.*?)(?=\n#+\s|\Z)'
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None

# =============================================================================
# FETCH TASKS
# =============================================================================

def fetch_tasks():
    """Fetch agent tasks from GitHub Issues."""
    import time
    
    # Check cache
    if _tasks_cache["data"] and time.time() < _tasks_cache["expires"]:
        return _tasks_cache["data"]
    
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    try:
        resp = requests.get(
            GITHUB_API,
            params={"labels": "agent-task", "state": "open", "per_page": 50},
            headers=headers,
            timeout=15
        )
        
        if resp.status_code != 200:
            return []
        
        issues = resp.json()
        tasks = []
        
        for issue in issues:
            amount = parse_task_amount(issue["title"])
            if amount == 0:
                continue
            
            body = issue.get("body", "") or ""
            task_type = get_task_type(body)
            
            task = {
                "id": issue["number"],
                "title": clean_title(issue["title"]),
                "amount": amount,
                "type": task_type,
                "frequency": get_frequency(body) if task_type == "recurring" else None,
                "description": extract_section(body, "Description") or body[:500] if body else None,
                "requirements": extract_section(body, "Requirements"),
                "submission_format": extract_section(body, "Submission") or extract_section(body, "How to Submit"),
                "url": issue["html_url"],
                "created_at": issue["created_at"],
                "labels": [l["name"] for l in issue.get("labels", []) if l["name"] != "agent-task"]
            }
            tasks.append(task)
        
        # Sort by amount descending
        tasks.sort(key=lambda x: x["amount"], reverse=True)
        
        # Update cache
        _tasks_cache["data"] = tasks
        _tasks_cache["expires"] = time.time() + CACHE_TTL
        
        return tasks
        
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        return []

# =============================================================================
# ENDPOINTS
# =============================================================================

@tasks_bp.route('/api/v1/tasks', methods=['GET'])
def list_tasks():
    """List all agent tasks."""
    tasks = fetch_tasks()
    
    # Optional filters
    task_type = request.args.get('type')  # recurring, one-time
    min_amount = request.args.get('min_amount', type=int)
    
    if task_type:
        tasks = [t for t in tasks if t["type"] == task_type]
    
    if min_amount:
        tasks = [t for t in tasks if t["amount"] >= min_amount]
    
    total_watt = sum(t["amount"] for t in tasks)
    
    return jsonify({
        "success": True,
        "count": len(tasks),
        "total_watt": total_watt,
        "tasks": tasks,
        "note": "Agent-only tasks. Not listed on website.",
        "docs": f"https://github.com/{GITHUB_REPO}/blob/main/CONTRIBUTING.md"
    })

@tasks_bp.route('/api/v1/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Get single task by ID."""
    tasks = fetch_tasks()
    
    for task in tasks:
        if task["id"] == task_id:
            return jsonify({
                "success": True,
                "task": task
            })
    
    return jsonify({
        "success": False,
        "error": "task_not_found",
        "message": f"Task #{task_id} not found or not open"
    }), 404
