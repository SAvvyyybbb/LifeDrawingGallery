import subprocess
import re
from pathlib import Path
from urllib.parse import quote

# Correct repo URL — used as fallback when Streamlit Cloud's remote is malformed
_FALLBACK_REPO_URL = "https://github.com/SAvvyyybbb/LifeDrawingGallery.git"

def run_cmd(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Git Command Failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()

def _clean_remote_url(repo_dir: Path) -> str:
    """Return the existing origin URL with credentials stripped, or '' on failure."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_dir), capture_output=True, text=True
    )
    url = result.stdout.strip()
    return re.sub(r'https://[^@]+@', 'https://', url)

def setup_git(repo_dir: Path, token: str, user: str = None, repo: str = None) -> str:
    """Configure bot identity and return an authenticated push URL.

    Returns the URL so callers can pass it directly to git_push(), which
    bypasses the remote config entirely — necessary because Streamlit Cloud
    may override git remote set-url via environment-level git configuration.
    """
    existing = _clean_remote_url(repo_dir)

    # A space in the URL means Streamlit Cloud injected a display name
    # ("Streamlit User") instead of the real GitHub username — unusable.
    if existing and ' ' not in existing and 'github.com' in existing:
        base_url = existing
    else:
        base_url = _FALLBACK_REPO_URL

    auth_url = base_url.replace('https://', f'https://x-access-token:{quote(token, safe="")}@', 1)
    run_cmd(["git", "config", "user.name", "Gallery Bot"], cwd=str(repo_dir))
    run_cmd(["git", "config", "user.email", "bot@lifedrawing.com"], cwd=str(repo_dir))
    return auth_url

def git_add(repo_dir: Path):
    # Strictly limit to Gallery UVs/ to prevent accidental staging of secrets
    run_cmd(["git", "add", "Gallery UVs/"], cwd=repo_dir)

def git_commit(repo_dir: Path, message: str) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain", "Gallery UVs/"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if not status.stdout.strip():
        return False
    run_cmd(["git", "commit", "-m", message], cwd=repo_dir)
    return True

def git_push(repo_dir: Path, auth_url: str):
    """Push using the authenticated URL directly — bypasses remote config."""
    run_cmd(["git", "push", auth_url, "HEAD:main"], cwd=str(repo_dir))
