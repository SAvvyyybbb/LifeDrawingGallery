import subprocess
import re
from pathlib import Path
from urllib.parse import quote

# Correct repo URL used as fallback when Streamlit Cloud's git remote is malformed
_FALLBACK_REPO_URL = "https://github.com/SAvvyyybbb/LifeDrawingGallery.git"

def run_cmd(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Git Command Failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()

def _get_clean_remote_url(repo_dir: Path) -> str:
    """Return the existing origin URL stripped of credentials, or '' on failure."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_dir), capture_output=True, text=True
    )
    url = result.stdout.strip()
    # Strip any embedded credentials (https://user:token@...)
    url = re.sub(r'https://[^@]+@', 'https://', url)
    return url

def setup_git(repo_dir: Path, token: str, user: str = None, repo: str = None):
    """Configure the git remote with an auth token and set bot identity.

    Reads the existing origin URL and injects the token.  If that URL is
    missing, empty, or contains spaces (a known Streamlit Cloud anomaly
    where GITHUB_USER resolves to a display name like "Streamlit User"),
    it falls back to the hardcoded _FALLBACK_REPO_URL so the push always
    targets the real repository regardless of what the secrets contain.
    """
    existing = _get_clean_remote_url(repo_dir)

    # A space in the URL means Streamlit Cloud injected a display name instead
    # of the actual GitHub username — the URL is unusable.
    if existing and ' ' not in existing and 'github.com' in existing:
        base_url = existing
    else:
        base_url = _FALLBACK_REPO_URL

    auth_url = base_url.replace('https://', f'https://x-access-token:{quote(token, safe="")}@', 1)
    run_cmd(["git", "remote", "set-url", "origin", auth_url], cwd=str(repo_dir))
    run_cmd(["git", "config", "user.name", "Gallery Bot"], cwd=str(repo_dir))
    run_cmd(["git", "config", "user.email", "bot@lifedrawing.com"], cwd=str(repo_dir))

def git_add(repo_dir: Path):
    # Strictly limit addition to Gallery UVs folder to prevent unexpected scope issues
    run_cmd(["git", "add", "Gallery UVs/"], cwd=repo_dir)

def git_commit(repo_dir: Path, message: str):
    # Check if there are changes to commit in Gallery UVs
    status = subprocess.run(["git", "status", "--porcelain", "Gallery UVs/"], cwd=repo_dir, capture_output=True, text=True)
    if not status.stdout.strip():
        return False # No changes

    run_cmd(["git", "commit", "-m", message], cwd=repo_dir)
    return True

def git_push(repo_dir: Path):
    run_cmd(["git", "push"], cwd=repo_dir)
