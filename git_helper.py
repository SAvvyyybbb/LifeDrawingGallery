import subprocess
from pathlib import Path
from urllib.parse import quote
import os

def run_cmd(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Git Command Failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()

def setup_git(repo_dir: Path, token: str, user: str, repo: str):
    """Configures the git remote and identity for Streamlit Cloud."""
    url = f"https://{quote(user, safe='')}:{quote(token, safe='')}@github.com/{user}/{repo}.git"
    run_cmd(["git", "remote", "set-url", "origin", url], cwd=repo_dir)
    run_cmd(["git", "config", "user.name", "Gallery Bot"], cwd=repo_dir)
    run_cmd(["git", "config", "user.email", "bot@lifedrawing.com"], cwd=repo_dir)

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
