#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
import os
import shutil

# ---------------- Helper Functions ----------------
def run_git_command(cmd, cwd=None):
    """Run a git command and return (success, stdout, stderr)"""
    try:
        result = subprocess.run(
            ["git"] + cmd,
            cwd=cwd,
            capture_output=True,
            text=True
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        print("Git not found. Install Git and ensure it's in your PATH.")
        sys.exit(1)

def find_git_root(path: Path = Path.cwd()) -> Path:
    """Detect git repository root"""
    success, stdout, stderr = run_git_command(["rev-parse", "--show-toplevel"], cwd=path)
    if success:
        return Path(stdout)
    print(f"No git repository found at {path}\n{stderr}")
    sys.exit(1)

def git_status(repo_root):
    success, stdout, stderr = run_git_command(["status", "--short"], cwd=repo_root)
    output = stdout or stderr
    print(output or "No changes detected.")
    return output

def git_add(repo_root):
    success, stdout, stderr = run_git_command(["add", "."], cwd=repo_root)
    output = stdout or stderr
    print(output or "All changes staged successfully.")

def git_commit(repo_root, message):
    success, stdout, stderr = run_git_command(["commit", "-m", message], cwd=repo_root)
    output = stdout + "\n" + stderr
    if "nothing to commit" in output.lower():
        print("Nothing to commit.")
    else:
        print("Committed successfully:\n", output.strip())

def git_push(repo_root, force=False):
    cmd = ["push"]
    if force:
        cmd.append("--force")
    success, stdout, stderr = run_git_command(cmd, cwd=repo_root)
    output = stdout + "\n" + stderr
    if success:
        print("Pushed successfully.")
    elif "non-fast-forward" in output.lower() or "rejected" in output.lower():
        if not force:
            print("Push rejected, attempting force push...")
            git_push(repo_root, force=True)
        else:
            print("Force push also failed:\n", output)
    else:
        print("Push failed:\n", output)

def git_pull(repo_root):
    success, stdout, stderr = run_git_command(["pull"], cwd=repo_root)
    output = stdout + "\n" + stderr
    if success:
        print("Pull successful:\n", output)
    else:
        print("Pull failed:\n", output)
        print("Resolve conflicts manually and retry.")

def auto_commit_message(status_output):
    if not status_output:
        return "Minor update"
    files = [line[3:] for line in status_output.splitlines()]
    if len(files) == 1:
        return f"Update {files[0]}"
    else:
        return f"Update {len(files)} files"

def remove_secrets(repo_root):
    secret_paths = [".gitignore/token.txt", ".secrets/*", "config.py", "token.txt"]
    cmd = ["git", "filter-repo"]
    for path in secret_paths:
        cmd += ["--path", path, "--invert-paths"]
    print(f"[Filter] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True)
        print(result.stdout)
        print(result.stderr)
        print("[Filter] Secrets removed. You may need to force push.")
    except FileNotFoundError:
        print("git-filter-repo not found. Install it and ensure it's in PATH.")

def clean_pyc(repo_root):
    pyc_files = list(Path(repo_root).rglob("*.pyc"))
    for f in pyc_files:
        os.remove(f)
    if pyc_files:
        print(f"Removed {len(pyc_files)} .pyc files.")

def quick_add_commit_push(repo_root):
    clean_pyc(repo_root)
    git_add(repo_root)
    status = git_status(repo_root)
    if not status:
        return
    msg = auto_commit_message(status)
    print(f"Auto commit message: {msg}")
    git_commit(repo_root, msg)
    git_push(repo_root)

# ---------------- Main Menu ----------------
def main():
    repo_root = find_git_root()
    print(f"\nGit Helper — Repo: {repo_root}\n")
    print("1) Status")
    print("2) Add all changes")
    print("3) Commit")
    print("4) Push")
    print("5) Pull")
    print("6) Quick: Add → Commit → Push")
    print("7) Remove secrets from repo history")
    print("0) Exit")

    choice = input("\nSelect an option: ").strip()

    if choice == "1":
        git_status(repo_root)
    elif choice == "2":
        git_add(repo_root)
    elif choice == "3":
        status = git_status(repo_root)
        msg = input(f"Enter commit message [{auto_commit_message(status)}]: ").strip() or auto_commit_message(status)
        git_commit(repo_root, msg)
    elif choice == "4":
        git_push(repo_root)
    elif choice == "5":
        git_pull(repo_root)
    elif choice == "6":
        quick_add_commit_push(repo_root)
    elif choice == "7":
        remove_secrets(repo_root)
    elif choice == "0":
        sys.exit()
    else:
        print("Invalid choice.")

    input("\nPress Enter to continue...")
    main()

if __name__ == "__main__":
    # Check Git is in PATH
    if shutil.which("git") is None:
        print("Git not found in PATH. Install Git and try again.")
        sys.exit(1)
    main()
