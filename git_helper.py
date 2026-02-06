#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
import os

# ---------------- Helper Functions ----------------
def run_git_command(cmd, cwd=None):
    """Run a git command and return (success, stdout+stderr)"""
    try:
        result = subprocess.run(
            ["git"] + cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout.strip() + ("\n" + result.stderr.strip())
    except FileNotFoundError:
        print("Git not found. Install Git and make sure it's in your PATH.")
        sys.exit(1)

def find_git_root(path: Path = Path.cwd()) -> Path:
    """Auto-detect the git repo root"""
    success, _ = run_git_command(["rev-parse", "--show-toplevel"], cwd=path)
    if success:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip())
    else:
        print("No git repository found in this folder or its parents.")
        sys.exit(1)

def git_status(repo_root):
    success, output = run_git_command(["status", "--short"], cwd=repo_root)
    print(output or "No changes detected.")
    return output

def git_add(repo_root):
    success, output = run_git_command(["add", "."], cwd=repo_root)
    if output:
        print(output)
    else:
        print("All changes staged successfully.")

def git_commit(repo_root, message):
    success, output = run_git_command(["commit", "-m", message], cwd=repo_root)
    if "nothing to commit" in output:
        print("Nothing to commit.")
    else:
        print("Committed successfully.\n", output)

def git_push(repo_root, force=False):
    cmd = ["push"]
    if force:
        cmd.append("--force")
    success, output = run_git_command(cmd, cwd=repo_root)
    if success:
        print("Pushed successfully.")
    else:
        print("Push failed:\n", output)
        if not force and ("non-fast-forward" in output or "rejected" in output):
            print("Attempting force push...")
            git_push(repo_root, force=True)

def git_pull(repo_root):
    success, output = run_git_command(["pull"], cwd=repo_root)
    if success:
        print("Pull successful.\n", output)
    else:
        print("Pull failed:\n", output)
        print("Resolve conflicts and try again.")

def auto_commit_message(status_output):
    """Generate a default commit message from changed files"""
    if not status_output:
        return "Minor update"
    lines = status_output.splitlines()
    files = [line[3:] for line in lines]  # XY filename
    if len(files) == 1:
        return f"Update {files[0]}"
    else:
        return f"Update {len(files)} files"

# ---------------- Secret Removal ----------------
def remove_secrets(repo_root):
    print("\n--- Removing secrets from repo history ---")
    secret_paths = [".gitignore/token.txt", ".secrets/*", "config.py", "token.txt"]
    cmd = ["git", "filter-repo"]
    for path in secret_paths:
        cmd += ["--path", path, "--invert-paths"]

    print(f"[Filter] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True)
        print(result.stdout)
        print(result.stderr)
        print("[Filter] Secrets removed from history.")
        print("⚠️ After running this, you need to force push: git push --force")
    except FileNotFoundError:
        print("git-filter-repo not found. Make sure it's installed and in PATH.")

# ---------------- Reset Everything ----------------
def reset_everything(repo_root):
    # Abort any in-progress merge
    success, output = run_git_command(["merge", "--abort"], cwd=repo_root)
    if success:
        print("⚠️ A merge was in progress. Aborted merge before reset...")
        print("Merge aborted successfully.")
    # Get the initial commit hash
    success, initial_commit = subprocess.getstatusoutput(
        'git rev-list --max-parents=0 HEAD'
    )
    if success != 0:
        print("Failed to find initial commit.")
        return

    initial_commit = initial_commit.strip()
    print(f"[Reset] Initial commit: {initial_commit}")
    # Soft reset to initial commit (keeps working tree and uncommitted changes)
    result = subprocess.run(
        ["git", "reset", "--soft", initial_commit],
        cwd=repo_root,
        text=True,
        capture_output=True
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    print("[Reset] All commits after the initial commit have been removed. Your files are untouched.")
    print("⚠️ You may need to force push: git push --force")

# ---------------- Remove .pyc ----------------
def clean_pyc(repo_root):
    pyc_files = list(Path(repo_root).rglob("*.pyc"))
    for f in pyc_files:
        os.remove(f)
    return len(pyc_files)

# ---------------- Quick Add → Commit → Push ----------------
def quick_add_commit_push(repo_root):
    """Quick workflow: clean pyc, add, commit, push with auto-force if needed."""
    # 1️⃣ Remove all .pyc files
    pyc_count = clean_pyc(repo_root)
    if pyc_count:
        print(f"Removed {pyc_count} .pyc files.")

    # 2️⃣ Stage all changes
    git_add(repo_root)

    # 3️⃣ Generate commit message
    status = git_status(repo_root)
    if not status:
        print("No changes to commit.")
        return
    msg = auto_commit_message(status)
    print(f"Auto commit message: {msg}")

    # 4️⃣ Commit
    git_commit(repo_root, msg)

    # 5️⃣ Push
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
    print("6) Quick: Add → Commit → Push (auto secret removal & pyc cleanup)")
    print("7) Remove all secrets from repo history")
    print("8) Reset everything (uncommit all commits)")
    print("0) Exit")

    choice = input("\nSelect an option: ").strip()

    if choice == "1":
        git_status(repo_root)
    elif choice == "2":
        git_add(repo_root)
    elif choice == "3":
        status = git_status(repo_root)
        default_msg = auto_commit_message(status)
        msg = input(f"Enter commit message [{default_msg}]: ").strip() or default_msg
        git_commit(repo_root, msg)
    elif choice == "4":
        git_push(repo_root)
    elif choice == "5":
        git_pull(repo_root)
    elif choice == "6":
        quick_add_commit_push(repo_root)
    elif choice == "7":
        remove_secrets(repo_root)
    elif choice == "8":
        reset_everything(repo_root)
    elif choice == "0":
        sys.exit()
    else:
        print("Invalid choice.")

    input("\nPress Enter to continue...")
    main()  # return to menu

if __name__ == "__main__":
    main()
