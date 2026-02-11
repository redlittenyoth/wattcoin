"""
AI Evaluation Logger
Persists AI evaluation outputs for quality analysis and system improvement.
Stores structured results from PR reviews, bounty evaluations, security audits,
and task verifications.
"""

import os
import json
from datetime import datetime, timezone

EVAL_LOG_DIR = os.getenv("EVAL_LOG_DIR", "data/eval_log")

# Evaluation type → subdirectory mapping
EVAL_TYPES = {
    "pr_review_public": "pr_reviews_public",
    "pr_review_internal": "pr_reviews_internal",
    "bounty_evaluation": "bounty_evaluations",
    "security_audit": "security_audits",
    "swarmsolve_audit": "swarmsolve_audits",
    "task_verification": "task_verifications",
}


def save_evaluation(eval_type, ai_response_text, metadata=None):
    """
    Save an AI evaluation result for analysis.

    Args:
        eval_type: Key from EVAL_TYPES (e.g. "pr_review_public")
        ai_response_text: Raw AI response string (usually JSON)
        metadata: Dict with context (pr_number, author, score, verdict, etc.)

    Returns: (filepath, error) tuple
    """
    subdir = EVAL_TYPES.get(eval_type)
    if not subdir:
        return None, f"Unknown eval_type: {eval_type}"

    save_dir = os.path.join(EVAL_LOG_DIR, subdir)
    os.makedirs(save_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    identifier = ""
    if metadata:
        if "pr_number" in metadata:
            identifier = f"_pr{metadata['pr_number']}"
        elif "issue_number" in metadata:
            identifier = f"_issue{metadata['issue_number']}"
        elif "task_id" in metadata:
            identifier = f"_task{metadata['task_id']}"
        elif "solution_id" in metadata:
            identifier = f"_sol{metadata['solution_id']}"

    filename = f"{timestamp}{identifier}_{eval_type}.json"
    filepath = os.path.join(save_dir, filename)

    parsed_response = None
    try:
        parsed_response = json.loads(ai_response_text)
    except (json.JSONDecodeError, TypeError):
        pass

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eval_type": eval_type,
        "ai_response_raw": ai_response_text,
        "ai_response_parsed": parsed_response,
        "metadata": metadata or {},
    }

    try:
        with open(filepath, 'w') as f:
            json.dump(record, f, indent=2)
        return filepath, None
    except Exception as e:
        print(f"[EVAL-LOG] Failed to save {eval_type}: {e}", flush=True)
        return None, str(e)
