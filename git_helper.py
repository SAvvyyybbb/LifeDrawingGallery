import subprocess
from pathlib import Path
import os

def run_cmd(cmd, cwd):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Git Command Failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()

def git_pull(repo_dir: Path):
    run_cmd(["git", "pull"], cwd=repo_dir)

def git_add(repo_dir: Path, path="."):
    run_cmd(["git", "add", path], cwd=repo_dir)

def git_commit(repo_dir: Path, message: str):
    # Check if there are changes to commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True)
    if not status.stdout.strip():
        return False # No changes
        
    run_cmd(["git", "commit", "-m", message], cwd=repo_dir)
    return True

def git_push(repo_dir: Path):
    run_cmd(["git", "push"], cwd=repo_dir)