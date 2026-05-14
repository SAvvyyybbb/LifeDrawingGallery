import subprocess
from pathlib import Path
from urllib.parse import quote
import os

def run_cmd(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Git Command Failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()

def setup_git(repo_dir: Path, token: str, user: str = None, repo: str = None):
    """Configures the git remote and identity for Streamlit Cloud.

    Reads the existing remote URL and injects the token — avoids any
    dependency on GITHUB_USER / GITHUB_REPO secrets, which can resolve
    to unexpected values on Streamlit Cloud.
    """
    import re
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(repo_dir), capture_output=True, text=True
    )
    existing = result.stdout.strip()

    if existing:
        # Strip any credentials already embedded in the URL
        clean = re.sub(r'https://[^@]+@', 'https://', existing)
    else:
        # Fallback: build URL from explicit user/repo if remote isn't set
        clean = f"https://github.com/{user}/{repo}.git"

    auth_url = clean.replace('https://', f'https://x-access-token:{quote(token, safe="")}@', 1)
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
