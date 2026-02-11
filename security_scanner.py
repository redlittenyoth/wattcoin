# =============================================================================
# FULL REPOSITORY SECURITY SCANNER v1.0.0
# Periodic scan of entire public repo for leaked secrets, vendor refs, PII
# Results stored in data/security_scan_results.json for admin dashboard
# =============================================================================

import os
import re
import json
import time
import base64
import requests
from datetime import datetime, timezone

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
SCAN_RESULTS_FILE = os.path.join(DATA_DIR, "security_scan_results.json")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
PUBLIC_REPO = os.getenv("REPO", "WattCoin-Org/wattcoin")

# File extensions to scan (skip images, binaries, fonts, etc.)
SCANNABLE_EXTENSIONS = {
    '.py', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', '.css',
    '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini',
    '.env', '.env.example', '.template', '.sh', '.bat', '.cmd',
    '.svg', '.xml', '.conf', '.config',
}

# Files/dirs to skip entirely
SKIP_PATHS = {
    'node_modules/', '.git/', 'package-lock.json', 'yarn.lock',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff',
    '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.pdf', '.zip',
    '.exe', '.msi', '.dll', '.so', '.dylib',
}

# Max file size to scan (skip huge generated files)
MAX_FILE_SIZE_KB = 500


# =============================================================================
# SCAN PATTERNS
# =============================================================================

SCAN_PATTERNS = [
    # --- Infrastructure Exposure ---
    {
        "id": "railway_url",
        "name": "Railway URL",
        "severity": "high",
        "pattern": re.compile(r'[a-zA-Z0-9_-]+\.up\.railway\.app', re.IGNORECASE),
        "description": "Hardcoded Railway deployment URL",
        "exclude_contexts": ["os.getenv", "env var", "BASE_URL"],
    },
    {
        "id": "admin_endpoint",
        "name": "Admin Endpoint Exposure",
        "severity": "medium",
        "pattern": re.compile(r'(?:href|url|fetch|redirect).*["\'/]admin[/"\'>\s]', re.IGNORECASE),
        "description": "Admin dashboard URL reference in public-facing code",
        "only_extensions": {'.html', '.htm', '.jsx', '.tsx', '.js', '.md'},
    },
    {
        "id": "internal_repo_ref",
        "name": "Internal Repo Reference",
        "severity": "high",
        "pattern": re.compile(r'wattcoin-internal', re.IGNORECASE),
        "description": "Reference to private internal repository",
        "exclude_contexts": ["os.getenv", "INTERNAL_REPO"],
    },
    {
        "id": "runpod_url",
        "name": "RunPod URL",
        "severity": "medium",
        "pattern": re.compile(r'[a-zA-Z0-9]+-\d+\.proxy\.runpod\.net', re.IGNORECASE),
        "description": "RunPod pod URL exposed",
        "exclude_contexts": ["os.getenv", "WSI_GATEWAY"],
    },

    # --- Secret / Credential Patterns ---
    {
        "id": "github_token",
        "name": "GitHub Token",
        "severity": "critical",
        "pattern": re.compile(r'ghp_[a-zA-Z0-9]{36}'),
        "description": "GitHub personal access token",
    },
    {
        "id": "anthropic_key",
        "name": "Anthropic API Key",
        "severity": "critical",
        "pattern": re.compile(r'sk-ant-api\d+-[a-zA-Z0-9_-]{20,}'),
        "description": "Anthropic API key",
    },
    {
        "id": "openai_key",
        "name": "OpenAI-style API Key",
        "severity": "critical",
        "pattern": re.compile(r'sk-[a-zA-Z0-9]{20,}'),
        "description": "OpenAI or compatible API key",
        "exclude_contexts": ["sk-ant-"],  # Already caught above
    },
    {
        "id": "generic_secret",
        "name": "Hardcoded Secret",
        "severity": "high",
        "pattern": re.compile(r'(?:secret|password|passwd|api_key|apikey|private_key|auth_token)\s*[=:]\s*["\'][a-zA-Z0-9_\-/.]{8,}["\']', re.IGNORECASE),
        "description": "Hardcoded secret or credential",
        "exclude_contexts": ["os.getenv", "env var", "example", "placeholder", "your_", '""', "''"],
    },
    {
        "id": "private_key_base58",
        "name": "Solana Private Key",
        "severity": "critical",
        "pattern": re.compile(r'(?:private.?key|keypair|secret.?key)\s*[=:]\s*["\'][1-9A-HJ-NP-Za-km-z]{64,88}["\']', re.IGNORECASE),
        "description": "Solana private key or keypair",
    },

    # --- Vendor References ---
    {
        "id": "xai_vendor",
        "name": "xAI/Grok Vendor Reference",
        "severity": "medium",
        "pattern": re.compile(r'(?:api\.x\.ai|xai\.com|grok-\d|XAI_API)', re.IGNORECASE),
        "description": "xAI or Grok vendor-specific reference",
        "exclude_contexts": ["os.getenv", "AI_CHAT_MODEL", "AI_API_BASE_URL"],
    },
    {
        "id": "petals_vendor",
        "name": "Petals Vendor Reference",
        "severity": "medium",
        "pattern": re.compile(r'(?:petals|PetalsNodeService|petals_)', re.IGNORECASE),
        "description": "Petals framework vendor reference",
        "exclude_contexts": ["import petals", "from petals", "pip install petals", "petals.cli"],  # Unavoidable package references
    },

    # --- Personal Identifiers ---
    {
        "id": "personal_name",
        "name": "Personal Name",
        "severity": "high",
        "pattern": re.compile(r'\b(?:Chris|Christopher)\b', re.IGNORECASE),
        "description": "Personal name found in public repo",
        "exclude_contexts": ["chris."],  # Avoid matching domain-like strings
    },
    {
        "id": "personal_email",
        "name": "Personal Email",
        "severity": "high",
        "pattern": re.compile(r'[a-zA-Z0-9._%+-]+@(?:gmail|outlook|hotmail|yahoo|protonmail)\.com', re.IGNORECASE),
        "description": "Personal email address",
    },

    # --- Private Document Exposure ---
    {
        "id": "private_doc",
        "name": "Private Document Reference",
        "severity": "high",
        "pattern": re.compile(r'(?:FUTURE_FEATURES|INTERNAL_PIPELINE|WSI_ARCHITECTURE|WSI_PROMPT_ARCHITECTURE|WSI_DEPLOYMENT)', re.IGNORECASE),
        "description": "Private document filename referenced in public repo",
        "exclude_contexts": ["security_scanner"],  # Don't flag ourselves
    },

    # --- WSI Architecture Exposure ---
    {
        "id": "wsi_training",
        "name": "WSI Training Architecture",
        "severity": "high",
        "pattern": re.compile(r'(?:wsi_replay|training.?data|self.?improv|fine.?tun|hivemind)', re.IGNORECASE),
        "description": "WSI self-improvement architecture details",
        "exclude_contexts": ["security_scanner"],  # Don't flag ourselves
    },
]


# =============================================================================
# SCAN LOGIC
# =============================================================================

def should_scan_file(filepath, size_kb=0):
    """Check if file should be scanned based on extension and path."""
    # Skip by path prefix/extension
    for skip in SKIP_PATHS:
        if skip in filepath.lower():
            return False

    # Check extension
    _, ext = os.path.splitext(filepath.lower())
    if ext and ext not in SCANNABLE_EXTENSIONS:
        return False

    # Skip oversized files
    if size_kb > MAX_FILE_SIZE_KB:
        return False

    return True


def check_exclude_context(line, exclude_contexts):
    """Check if line matches any exclusion context (false positive filter)."""
    if not exclude_contexts:
        return False
    for ctx in exclude_contexts:
        if ctx.lower() in line.lower():
            return True
    return False


def scan_file_content(filepath, content, patterns=None):
    """Scan a single file's content against all patterns.
    
    Returns list of findings.
    """
    if patterns is None:
        patterns = SCAN_PATTERNS

    findings = []
    lines = content.split('\n')

    for pattern_def in patterns:
        only_ext = pattern_def.get("only_extensions")
        if only_ext:
            _, ext = os.path.splitext(filepath.lower())
            if ext not in only_ext:
                continue

        for line_num, line in enumerate(lines, 1):
            if pattern_def["pattern"].search(line):
                # Check exclusion contexts
                if check_exclude_context(line, pattern_def.get("exclude_contexts")):
                    continue

                findings.append({
                    "pattern_id": pattern_def["id"],
                    "pattern_name": pattern_def["name"],
                    "severity": pattern_def["severity"],
                    "description": pattern_def["description"],
                    "file": filepath,
                    "line": line_num,
                    "content": line.strip()[:200],  # Truncate long lines
                })

    return findings


def fetch_repo_files():
    """Fetch all files from public repo via GitHub API (recursive tree)."""
    if not GITHUB_TOKEN:
        return None, "GITHUB_TOKEN not configured"

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    # Get default branch SHA
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{PUBLIC_REPO}/git/ref/heads/main",
            headers=headers, timeout=15
        )
        resp.raise_for_status()
        commit_sha = resp.json()["object"]["sha"]
    except Exception as e:
        return None, f"Failed to get repo ref: {e}"

    # Get recursive tree
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{PUBLIC_REPO}/git/trees/{commit_sha}?recursive=1",
            headers=headers, timeout=30
        )
        resp.raise_for_status()
        tree = resp.json().get("tree", [])
    except Exception as e:
        return None, f"Failed to get repo tree: {e}"

    files = []
    for item in tree:
        if item["type"] == "blob":
            size_kb = item.get("size", 0) / 1024
            if should_scan_file(item["path"], size_kb):
                files.append({
                    "path": item["path"],
                    "sha": item["sha"],
                    "size_kb": round(size_kb, 1),
                })

    return files, None


def fetch_file_content(file_sha):
    """Fetch file content by blob SHA."""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{PUBLIC_REPO}/git/blobs/{file_sha}",
            headers=headers, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")
    except Exception as e:
        return None


# Files that contain scan pattern definitions — exclude from scanning (self-reference)
SCANNER_EXCLUSIONS = {
    "security_scanner.py",
    ".github/scripts/leak_scanner.py",
    "scraper_errors.py",  # Contains test constants, not real secrets
    "internal_pipeline.py",  # Legitimately references internal repo
}


def run_full_scan():
    """Run full repository security scan.
    
    Returns dict with scan results.
    """
    start_time = time.time()
    scan_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print(f"[SECURITY-SCAN] Starting full repo scan {scan_id}...", flush=True)

    # Fetch file list
    files, error = fetch_repo_files()
    if error:
        result = {
            "scan_id": scan_id,
            "status": "error",
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": round(time.time() - start_time, 1),
        }
        save_results(result)
        return result

    print(f"[SECURITY-SCAN] Found {len(files)} scannable files", flush=True)

    all_findings = []
    files_scanned = 0
    files_errored = 0

    for file_info in files:
        content = fetch_file_content(file_info["sha"])
        if content is None:
            files_errored += 1
            continue

        findings = scan_file_content(file_info["path"], content)
        all_findings.extend(findings)
        files_scanned += 1

        # Rate limit: GitHub API allows 5000/hr, be conservative
        if files_scanned % 50 == 0:
            time.sleep(0.5)

    duration = round(time.time() - start_time, 1)

    # Summarize by severity
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev = f.get("severity", "medium")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Group findings by file
    by_file = {}
    for f in all_findings:
        fp = f["file"]
        if fp not in by_file:
            by_file[fp] = []
        by_file[fp].append(f)

    result = {
        "scan_id": scan_id,
        "status": "clean" if len(all_findings) == 0 else "findings",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration,
        "files_total": len(files),
        "files_scanned": files_scanned,
        "files_errored": files_errored,
        "findings_total": len(all_findings),
        "severity_counts": severity_counts,
        "findings_by_file": by_file,
        "findings": all_findings,
        "patterns_checked": len(SCAN_PATTERNS),
    }

    print(f"[SECURITY-SCAN] Scan complete: {files_scanned} files, {len(all_findings)} findings, {duration}s", flush=True)

    save_results(result)
    return result


def save_results(result):
    """Save scan results to data file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SCAN_RESULTS_FILE, 'w') as f:
            json.dump(result, f, indent=2)
    except Exception as e:
        print(f"[SECURITY-SCAN] Failed to save results: {e}", flush=True)


def load_latest_results():
    """Load most recent scan results."""
    try:
        with open(SCAN_RESULTS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# =============================================================================
# SCHEDULED SCAN (called by cron thread)
# =============================================================================

def scheduled_scan():
    """Run scan on schedule. Called by cron daemon thread."""
    try:
        result = run_full_scan()
        status = result.get("status", "unknown")
        count = result.get("findings_total", 0)
        print(f"[SECURITY-SCAN] Scheduled scan complete: {status}, {count} findings", flush=True)
    except Exception as e:
        print(f"[SECURITY-SCAN] Scheduled scan failed: {e}", flush=True)
