"""
WSI Training Replay System
Generate training data from historical PRs and challenge tests without affecting production
"""

import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
import requests

# Create Blueprint
wsi_replay_bp = Blueprint('wsi_replay', __name__)

# Environment variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "WattCoin-Org/wattcoin")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
WSI_TRAINING_DIR = "data/wsi_training"
WSI_CHALLENGES_DIR = "data/wsi_challenges"

# =============================================================================
# AUTH HELPER
# =============================================================================

def check_admin_auth(data):
    """
    Check admin authentication via admin_key in request data.
    Same pattern as SwarmSolve admin auth.
    
    Returns: (is_admin: bool, error_response: tuple or None)
    """
    admin_key = (data.get("admin_key") or "").strip()
    expected_admin = ADMIN_API_KEY
    is_admin = bool(expected_admin and admin_key == expected_admin)
    
    if not is_admin:
        return False, (jsonify({"error": "Admin authentication required. Include admin_key in request body."}), 403)
    
    return True, None

# =============================================================================
# GITHUB API
# =============================================================================

def github_headers():
    """Get GitHub API headers with auth."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


def fetch_pr_info(pr_number, repo=None):
    """
    Fetch PR details from GitHub API.
    
    Returns: (pr_info dict, error string)
    pr_info contains: number, title, body, author, diff, files_changed, additions, deletions
    """
    check_repo = repo or GITHUB_REPO
    
    try:
        # Fetch PR metadata
        url = f"https://api.github.com/repos/{check_repo}/pulls/{pr_number}"
        resp = requests.get(url, headers=github_headers(), timeout=30)
        
        if resp.status_code != 200:
            return None, f"GitHub API error: HTTP {resp.status_code}"
        
        pr_data = resp.json()
        
        # Fetch PR diff
        diff_headers = github_headers()
        diff_headers["Accept"] = "application/vnd.github.v3.diff"
        diff_resp = requests.get(url, headers=diff_headers, timeout=30)
        
        if diff_resp.status_code != 200:
            return None, f"Failed to fetch diff: HTTP {diff_resp.status_code}"
        
        pr_info = {
            "number": pr_number,
            "title": pr_data.get("title", ""),
            "body": pr_data.get("body", ""),
            "author": pr_data.get("user", {}).get("login", "unknown"),
            "diff": diff_resp.text,
            "files_changed": pr_data.get("changed_files", 0),
            "additions": pr_data.get("additions", 0),
            "deletions": pr_data.get("deletions", 0),
            "repo": check_repo
        }
        
        return pr_info, None
        
    except Exception as e:
        return None, f"Error fetching PR: {str(e)}"

# =============================================================================
# STORAGE
# =============================================================================

def save_replay_data(pr_number, data_type, data):
    """
    Save replay data to wsi_training/replay/ directory.
    
    Args:
        pr_number: PR number being replayed
        data_type: "review" or "security"
        data: Dict containing full replay results
    
    Returns:
        filepath or None
    """
    try:
        # Create replay directory
        replay_dir = os.path.join(WSI_TRAINING_DIR, "replay")
        os.makedirs(replay_dir, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_pr{pr_number}_{data_type}.json"
        filepath = os.path.join(replay_dir, filename)
        
        # Add timestamp
        data["timestamp"] = datetime.utcnow().isoformat() + "Z"
        data["replay_type"] = data_type
        data["pr_number"] = pr_number
        
        # Save
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[WSI-REPLAY] Saved: replay/{filename}", flush=True)
        return filepath
        
    except Exception as e:
        print(f"[WSI-REPLAY] Failed to save {data_type} for PR #{pr_number}: {e}", flush=True)
        return None


def save_challenge_result(challenge_id, data):
    """Save challenge run results."""
    try:
        challenge_dir = os.path.join(WSI_TRAINING_DIR, "challenges")
        os.makedirs(challenge_dir, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{challenge_id}.json"
        filepath = os.path.join(challenge_dir, filename)
        
        data["timestamp"] = datetime.utcnow().isoformat() + "Z"
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[WSI-REPLAY] Saved: challenges/{filename}", flush=True)
        return filepath
        
    except Exception as e:
        print(f"[WSI-REPLAY] Failed to save challenge {challenge_id}: {e}", flush=True)
        return None


def save_annotation(pr_number, annotation_data):
    """Save score correction annotation."""
    try:
        annotation_dir = os.path.join(WSI_TRAINING_DIR, "annotations")
        os.makedirs(annotation_dir, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_pr{pr_number}.json"
        filepath = os.path.join(annotation_dir, filename)
        
        annotation_data["timestamp"] = datetime.utcnow().isoformat() + "Z"
        annotation_data["pr_number"] = pr_number
        
        with open(filepath, 'w') as f:
            json.dump(annotation_data, f, indent=2)
        
        print(f"[WSI-REPLAY] Saved: annotations/{filename}", flush=True)
        return filepath
        
    except Exception as e:
        print(f"[WSI-REPLAY] Failed to save annotation for PR #{pr_number}: {e}", flush=True)
        return None

# =============================================================================
# ENDPOINT 1: REPLAY HISTORICAL PR
# =============================================================================

@wsi_replay_bp.route('/admin/api/wsi/replay', methods=['POST'])
def replay_pr():
    """
    Replay a historical PR through current AI review + security scan.
    Does NOT affect the PR — only generates training data.
    
    Body: {"admin_key": "<ADMIN_API_KEY>", "pr_number": 164, "store": true}
    """
    try:
        data = request.get_json()
        
        # Admin auth check
        is_admin, error_response = check_admin_auth(data)
        if not is_admin:
            return error_response
        
        pr_number = data.get("pr_number")
        store = data.get("store", True)
        
        if not pr_number:
            return jsonify({"error": "pr_number required"}), 400
        
        # Fetch PR info
        print(f"[WSI-REPLAY] Fetching PR #{pr_number}...", flush=True)
        pr_info, error = fetch_pr_info(pr_number)
        
        if error:
            return jsonify({"error": error}), 400
        
        results = {
            "pr_number": pr_number,
            "pr_info": {
                "title": pr_info["title"],
                "author": pr_info["author"],
                "files_changed": pr_info["files_changed"]
            }
        }
        
        # Run AI code review
        print(f"[WSI-REPLAY] Running AI review for PR #{pr_number}...", flush=True)
        try:
            from admin_blueprint import call_ai_review
            review_result = call_ai_review(pr_info)
            results["review"] = review_result
            
            if store:
                save_replay_data(pr_number, "review", {
                    "pr_info": pr_info,
                    "review_result": review_result
                })
        except Exception as e:
            results["review"] = {"error": str(e)}
        
        # Run security scan
        print(f"[WSI-REPLAY] Running security scan for PR #{pr_number}...", flush=True)
        try:
            from pr_security import ai_security_scan_pr
            passed, report, scan_ran = ai_security_scan_pr(pr_number)
            results["security"] = {
                "passed": passed,
                "report": report,
                "scan_ran": scan_ran
            }
            
            if store:
                save_replay_data(pr_number, "security", {
                    "pr_info": pr_info,
                    "security_result": {
                        "passed": passed,
                        "report": report,
                        "scan_ran": scan_ran
                    }
                })
        except Exception as e:
            results["security"] = {"error": str(e)}
        
        print(f"[WSI-REPLAY] Completed replay for PR #{pr_number}", flush=True)
        return jsonify(results), 200
        
    except Exception as e:
        print(f"[WSI-REPLAY] Error in replay_pr: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@wsi_replay_bp.route('/admin/api/wsi/replay-batch', methods=['POST'])
def replay_batch():
    """
    Replay multiple PRs in batch.
    
    Body: {"admin_key": "<ADMIN_API_KEY>", "pr_numbers": [130, 131, 150], "store": true}
    """
    try:
        data = request.get_json()
        
        # Admin auth check
        is_admin, error_response = check_admin_auth(data)
        if not is_admin:
            return error_response
        
        pr_numbers = data.get("pr_numbers", [])
        store = data.get("store", True)
        
        if not pr_numbers or not isinstance(pr_numbers, list):
            return jsonify({"error": "pr_numbers array required"}), 400
        
        if len(pr_numbers) > 20:
            return jsonify({"error": "Maximum 20 PRs per batch"}), 400
        
        results = {
            "total": len(pr_numbers),
            "completed": 0,
            "failed": 0,
            "prs": {}
        }
        
        for pr_number in pr_numbers:
            print(f"[WSI-REPLAY] Batch processing PR #{pr_number}...", flush=True)
            
            # Fetch PR info
            pr_info, error = fetch_pr_info(pr_number)
            
            if error:
                results["prs"][pr_number] = {"error": error}
                results["failed"] += 1
                continue
            
            pr_results = {
                "title": pr_info["title"],
                "author": pr_info["author"]
            }
            
            # Run AI review
            try:
                from admin_blueprint import call_ai_review
                review_result = call_ai_review(pr_info)
                pr_results["review_score"] = review_result.get("score")
                pr_results["review_passed"] = review_result.get("passed")
                
                if store:
                    save_replay_data(pr_number, "review", {
                        "pr_info": pr_info,
                        "review_result": review_result
                    })
            except Exception as e:
                pr_results["review_error"] = str(e)
            
            # Run security scan
            try:
                from pr_security import ai_security_scan_pr
                passed, report, scan_ran = ai_security_scan_pr(pr_number)
                pr_results["security_passed"] = passed
                
                if store:
                    save_replay_data(pr_number, "security", {
                        "pr_info": pr_info,
                        "security_result": {
                            "passed": passed,
                            "report": report,
                            "scan_ran": scan_ran
                        }
                    })
            except Exception as e:
                pr_results["security_error"] = str(e)
            
            results["prs"][pr_number] = pr_results
            results["completed"] += 1
        
        print(f"[WSI-REPLAY] Batch completed: {results['completed']}/{results['total']}", flush=True)
        return jsonify(results), 200
        
    except Exception as e:
        print(f"[WSI-REPLAY] Error in replay_batch: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# =============================================================================
# ENDPOINT 2: CHALLENGE RUNNER
# =============================================================================

@wsi_replay_bp.route('/admin/api/wsi/challenge-run', methods=['POST'])
def challenge_run():
    """
    Run AI review + security on challenge diffs from manifest.
    
    Body: {"admin_key": "<ADMIN_API_KEY>", "challenge_set": "all"}
    """
    try:
        data = request.get_json()
        
        # Admin auth check
        is_admin, error_response = check_admin_auth(data)
        if not is_admin:
            return error_response
        
        challenge_set = data.get("challenge_set", "all")
        
        # Load manifest
        manifest_path = os.path.join(WSI_CHALLENGES_DIR, "manifest.json")
        
        if not os.path.exists(manifest_path):
            return jsonify({"error": "manifest.json not found in data/wsi_challenges/"}), 404
        
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        challenges = manifest.get("challenges", [])
        
        if challenge_set != "all":
            # Filter by set name
            challenges = [c for c in challenges if c.get("set") == challenge_set]
        
        if not challenges:
            return jsonify({"error": f"No challenges found for set '{challenge_set}'"}), 404
        
        results = {
            "total": len(challenges),
            "passed": 0,
            "failed": 0,
            "challenges": []
        }
        
        for challenge in challenges:
            challenge_id = challenge.get("id")
            diff_file = challenge.get("diff_file")
            expected_verdict = challenge.get("expected_verdict")
            expected_score_min = challenge.get("expected_score_min")
            expected_score_max = challenge.get("expected_score_max")
            
            print(f"[WSI-REPLAY] Running challenge: {challenge_id}", flush=True)
            
            # Load diff file
            diff_path = os.path.join(WSI_CHALLENGES_DIR, diff_file)
            
            if not os.path.exists(diff_path):
                results["challenges"].append({
                    "id": challenge_id,
                    "status": "error",
                    "error": f"Diff file not found: {diff_file}"
                })
                results["failed"] += 1
                continue
            
            with open(diff_path, 'r') as f:
                diff_text = f.read()
            
            # Create mock PR info
            pr_info = {
                "number": 0,
                "title": challenge.get("title", f"Challenge: {challenge_id}"),
                "body": challenge.get("description", ""),
                "author": "wsi_challenge",
                "diff": diff_text,
                "files_changed": 1,
                "additions": 10,
                "deletions": 5,
                "repo": "challenge"
            }
            
            challenge_result = {
                "id": challenge_id,
                "expected_verdict": expected_verdict,
                "expected_score_range": f"{expected_score_min}-{expected_score_max}"
            }
            
            # Run AI review
            try:
                from admin_blueprint import call_ai_review
                review_result = call_ai_review(pr_info)
                
                actual_score = review_result.get("score", 0)
                actual_passed = review_result.get("passed", False)
                actual_verdict = "PASS" if actual_passed else "FAIL"
                
                challenge_result["actual_verdict"] = actual_verdict
                challenge_result["actual_score"] = actual_score
                
                # Check if it matches expectations
                verdict_match = (actual_verdict == expected_verdict)
                score_match = (expected_score_min <= actual_score <= expected_score_max)
                
                challenge_result["verdict_match"] = verdict_match
                challenge_result["score_match"] = score_match
                challenge_result["status"] = "passed" if (verdict_match and score_match) else "failed"
                
                if challenge_result["status"] == "passed":
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                
                # Store result
                save_challenge_result(challenge_id, {
                    "challenge": challenge,
                    "review_result": review_result,
                    "verdict_match": verdict_match,
                    "score_match": score_match
                })
                
            except Exception as e:
                challenge_result["status"] = "error"
                challenge_result["error"] = str(e)
                results["failed"] += 1
            
            results["challenges"].append(challenge_result)
        
        print(f"[WSI-REPLAY] Challenge run completed: {results['passed']}/{results['total']} passed", flush=True)
        return jsonify(results), 200
        
    except Exception as e:
        print(f"[WSI-REPLAY] Error in challenge_run: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

# =============================================================================
# ENDPOINT 3: SCORE CORRECTIONS
# =============================================================================

@wsi_replay_bp.route('/admin/api/wsi/annotate', methods=['POST'])
def annotate():
    """
    Store score correction annotation for a PR.
    Pure storage — highest-value training signal.
    
    Body: {
        "admin_key": "<ADMIN_API_KEY>",
        "pr_number": 130,
        "corrected_score": 3,
        "corrected_verdict": "FAIL",
        "reason": "Wallet injection detected but AI missed it"
    }
    """
    try:
        data = request.get_json()
        
        # Admin auth check
        is_admin, error_response = check_admin_auth(data)
        if not is_admin:
            return error_response
        
        pr_number = data.get("pr_number")
        corrected_score = data.get("corrected_score")
        corrected_verdict = data.get("corrected_verdict")
        reason = data.get("reason", "")
        
        if not pr_number:
            return jsonify({"error": "pr_number required"}), 400
        
        if corrected_score is None and not corrected_verdict:
            return jsonify({"error": "corrected_score or corrected_verdict required"}), 400
        
        annotation_data = {
            "pr_number": pr_number,
            "corrected_score": corrected_score,
            "corrected_verdict": corrected_verdict,
            "reason": reason,
            "annotator": "admin"
        }
        
        filepath = save_annotation(pr_number, annotation_data)
        
        if filepath:
            print(f"[WSI-REPLAY] Annotation saved for PR #{pr_number}", flush=True)
            return jsonify({
                "success": True,
                "pr_number": pr_number,
                "filepath": filepath
            }), 200
        else:
            return jsonify({"error": "Failed to save annotation"}), 500
        
    except Exception as e:
        print(f"[WSI-REPLAY] Error in annotate: {e}", flush=True)
        return jsonify({"error": str(e)}), 500
