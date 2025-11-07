#!/usr/bin/env python3
import yaml
import subprocess
import sys
import time
import re
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
import hashlib

# --- Paths / Config ---

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

REPO_LIST_FILE = PROJECT_ROOT / 'repositories.yaml'
RAISIN_SCRIPT = PROJECT_ROOT / 'raisin.py'
SRC_DIR = PROJECT_ROOT / 'src'

# --- Dashboard Configuration ---
DASHBOARD_REPO_URL = "git@github.com:raionrobotics/raionrobotics_ci_dashboard.git"
DASHBOARD_PATH = SCRIPT_DIR / 'raionrobotics_ci_dashboard'
DASHBOARD_README = DASHBOARD_PATH / 'README.md'
# --------------------------------


# ------------- Git helpers -------------

def run_git_command(command, cwd=None):
    print(f"\n[Git]: {' '.join(['git'] + command)}")
    try:
        subprocess.run(['git'] + command, cwd=cwd, check=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"--- GIT COMMAND FAILED (Exit Code: {e.returncode}) ---", file=sys.stderr)
        return False


def run_git_capture(command, cwd=None, timeout=60):
    try:
        res = subprocess.run(['git'] + command, cwd=cwd, check=True, text=True,
                             capture_output=True, timeout=timeout)
        return True, res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"--- GIT COMMAND FAILED (Exit Code: {e.returncode}) ---", file=sys.stderr)
        return False, ""
    except Exception as e:
        print(f"--- GIT COMMAND ERROR: {e} ---", file=sys.stderr)
        return False, ""


def ensure_dashboard_repo():
    if DASHBOARD_PATH.exists():
        print(f"Dashboard repo found at: {DASHBOARD_PATH}")
        return True
    print(f"Cloning dashboard repo into {DASHBOARD_PATH}...")
    if not run_git_command(['clone', DASHBOARD_REPO_URL, str(DASHBOARD_PATH)]):
        print("FATAL: Could not clone dashboard repo. Exiting.", file=sys.stderr)
        sys.exit(1)
    return True


def _detect_dashboard_branch():
    ok, upstream = run_git_capture(['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'], cwd=DASHBOARD_PATH)
    if ok and upstream and '/' in upstream:
        return upstream.split('/', 1)[1]
    ok, head = run_git_capture(['rev-parse', '--abbrev-ref', 'origin/HEAD'], cwd=DASHBOARD_PATH)
    if ok and head.startswith('origin/'):
        return head.split('/', 1)[1]
    return 'main'


def pull_dashboard_repo():
    print("Pulling latest dashboard changes...")
    branch = _detect_dashboard_branch()
    run_git_command(['fetch', '--all', '--prune'], cwd=DASHBOARD_PATH)
    ok, local_branches = run_git_capture(['branch', '--list', branch], cwd=DASHBOARD_PATH)
    if ok and not local_branches.strip():
        run_git_command(['checkout', '-B', branch, f'origin/{branch}'], cwd=DASHBOARD_PATH)
    if not run_git_command(['pull', '--rebase', 'origin', branch], cwd=DASHBOARD_PATH):
        run_git_command(['pull', '--rebase'], cwd=DASHBOARD_PATH)


def run_build_command(command, cwd):
    print(f"\n[Running]: {' '.join(command)}")
    try:
        subprocess.run(command, cwd=cwd, check=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"--- COMMAND FAILED (Exit Code: {e.returncode}) ---", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"Error: Command '{command[0]}' not found.", file=sys.stderr)
        return False


# ------------- SHA helpers -------------

def get_local_branch_tip(repo_path: Path, branch: str = 'main'):
    if not repo_path.is_dir():
        print(f"  Warning: Local repo not found at {repo_path}.", file=sys.stderr)
        return "N/A"
    if not (repo_path / '.git').exists():
        print(f"  Warning: No .git directory found at {repo_path}.", file=sys.stderr)
        return "N/A"
    try:
        res = subprocess.run(['git', 'rev-parse', branch], cwd=repo_path,
                             capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        try:
            res = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo_path,
                                 capture_output=True, text=True, check=True)
            print(f"  Note: '{branch}' not found in {repo_path.name}; using HEAD instead.", file=sys.stderr)
            return res.stdout.strip()
        except Exception as e:
            print(f"  Warning: Could not get local SHA for {repo_path}: {e}", file=sys.stderr)
            return "N/A"


def get_local_package_commit_sha(package_name: str):
    return get_local_branch_tip(SRC_DIR / package_name, 'main')


def _repo_cache_dir(repo_url: str) -> Path:
    h = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:16]
    return Path(gettempdir()) / f"repo_cache_{h}"


def _resolve_default_branch(repo_url: str) -> str | None:
    try:
        res = subprocess.run(['git', 'ls-remote', '--symref', repo_url, 'HEAD'],
                             capture_output=True, text=True, check=True, timeout=60)
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith('ref:') and line.endswith('HEAD'):
                ref = line.split()[1]
                if ref.startswith('refs/heads/'):
                    return ref.split('/', 2)[2]
        return None
    except Exception as e:
        print(f"  Error: could not resolve default branch for {repo_url}: {e}", file=sys.stderr)
        return None


def _get_latest_commit_via_shallow_clone(repo_url: str, branch: str = 'main') -> tuple[str | None, str]:
    cache_dir = _repo_cache_dir(repo_url)
    try:
        if cache_dir.exists():
            run_git_command(['fetch', '--all', '--prune', '--depth', '1'], cwd=cache_dir)
            run_git_command(['fetch', 'origin', branch, '--depth', '1'], cwd=cache_dir)
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
            ok = run_git_command(['clone', '--depth', '1', '--no-tags', '-b', branch, repo_url, str(cache_dir)])
            if not ok:
                return None, 'clone-failed'
        ok, sha = run_git_capture(['rev-parse', f'origin/{branch}'], cwd=cache_dir)
        return (sha if ok and sha else None), 'shallow-clone'
    except Exception as e:
        print(f"  Error (shallow clone): {e}", file=sys.stderr)
        return None, 'shallow-error'


def source_repo_url_from_release(url_with_release: str) -> str:
    """
    Transform .../NAME_release.git -> .../NAME.git
    Works for SSH and HTTPS remotes. If no _release suffix, returns the URL unchanged (normalized to end with .git).
    """
    m = re.match(r'^(?P<prefix>.+/)(?P<name>[^/]+?)(?P<dotgit>\.git)?$', url_with_release)
    if not m:
        return url_with_release
    prefix = m.group('prefix')
    name = m.group('name')
    if name.endswith('_release'):
        name = name[:-8]  # drop suffix
    return f"{prefix}{name}.git"


def get_latest_commit_from_source_repo(repo_url_release: str) -> tuple[str | None, str, str, str]:
    """
    Using the release URL (from repositories.yaml), compute the *source* URL (without _release),
    then get the SHA of refs/heads/main there.
    Returns (sha, source_url, ref_used, method).
    """
    source_url = source_repo_url_from_release(repo_url_release)

    # 1) Exact refs/heads/main on source URL
    try:
        res = subprocess.run(['git', 'ls-remote', source_url, 'refs/heads/main'],
                             capture_output=True, text=True, check=True, timeout=60)
        out = res.stdout.strip()
        if out:
            sha = out.split()[0]
            return sha, source_url, 'refs/heads/main', 'ls-remote'
    except Exception as e:
        print(f"  Warning: ls-remote refs/heads/main failed for {source_url}: {e}", file=sys.stderr)

    # 2) Resolve default branch and retry on source URL
    default_branch = _resolve_default_branch(source_url)
    if default_branch and default_branch != 'main':
        try:
            res = subprocess.run(['git', 'ls-remote', source_url, f'refs/heads/{default_branch}'],
                                 capture_output=True, text=True, check=True, timeout=60)
            out = res.stdout.strip()
            if out:
                sha = out.split()[0]
                return sha, source_url, f'refs/heads/{default_branch}', 'ls-remote(default)'
        except Exception as e:
            print(f"  Warning: ls-remote refs/heads/{default_branch} failed for {source_url}: {e}", file=sys.stderr)

    # 3) Final fallback via shallow clone
    sha, method = _get_latest_commit_via_shallow_clone(source_url, default_branch or 'main')
    return sha, source_url, f"origin/{default_branch or 'main'}", method


# ------------- Build sequence -------------

class BuildSequence:
    def __init__(self, package_names):
        self.package_names = package_names
        self.results = []  # (project_name, status_emoji, commit_sha, build_type)
        self.python_exe = sys.executable
        self.working_dir = PROJECT_ROOT
        self.master_sha = "N/A"

    def _run_and_store(self, command, project_name, commit_sha, build_type):
        success = run_build_command(command, self.working_dir)
        status_emoji = "✅ **Success**" if success else "❌ **Failure**"
        self.results.append((project_name, status_emoji, commit_sha, build_type))
        return success

    def _insert_rows_into_markdown(self, content: str, rows: str) -> str:
        divider_pattern = re.compile(
            r"(^\|\s*:?-{3,}\s*\|\s*:?-{3,}\s*\|\s*:?-{3,}\s*\|\s*:?-{3,}\s*\|\s*:?-{3,}\s*\|\s*:?-{3,}\s*\|\s*$)",
            re.MULTILINE
        )
        m = divider_pattern.search(content)
        if m:
            insert_pos = m.end()
            return content[:insert_pos] + "\n" + rows + content[insert_pos:]
        else:
            fallback_header = (
                "\n\n"
                "| Project | Status | Timestamp | Commit | Source | Build |\n"
                "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            )
            return content + fallback_header + rows + "\n"

    def report_all_to_dashboard(self):
        if not self.results:
            print("No build results to report.")
            return

        print("\n--- 🚀 Updating Build Dashboard with all results ---")
        pull_dashboard_repo()

        if not DASHBOARD_README.exists():
            print(f"Error: Dashboard README not found at {DASHBOARD_README}", file=sys.stderr)
            return

        try:
            with open(DASHBOARD_README, 'r', encoding='utf-8') as f:
                content = f.read()

            date_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            date_time_utc = f"{date_time} UTC"

            new_rows = []
            for (project_name, status_emoji, commit_sha, build_type) in self.results:
                commit_sha_short = (commit_sha or "N/A")[:7]
                new_rows.append(
                    f"| {project_name} | {status_emoji} | `{date_time_utc}` | "
                    f"`{commit_sha_short}` | `local-watcher` | `{build_type}` |"
                )
            all_new_rows = "\n".join(new_rows)

            content = re.sub(r"\*Last Update:\s*`[^`]*`\*", f"*Last Update: `{date_time_utc}`*", content)
            content = self._insert_rows_into_markdown(content, all_new_rows)

            with open(DASHBOARD_README, 'w', encoding='utf-8') as f:
                f.write(content)

            ok, status = run_git_capture(['status', '--porcelain'], cwd=DASHBOARD_PATH)
            if ok and not status.strip():
                print("No changes detected in README.md; skipping commit/push.")
                print("--- ✅ Dashboard Update Complete (no-op) ---")
                return

            print("Committing and pushing dashboard update...")
            if not run_git_command(['add', 'README.md'], cwd=DASHBOARD_PATH):
                return

            num_success = sum(1 for r in self.results if "Success" in r[1])
            num_fail = len(self.results) - num_success
            commit_msg = f"docs(bot): CI build complete ({num_success} success, {num_fail} fail)"

            if not run_git_command(['commit', '-m', commit_msg], cwd=DASHBOARD_PATH):
                return

            branch = _detect_dashboard_branch()
            if not run_git_command(['push', 'origin', branch], cwd=DASHBOARD_PATH):
                run_git_command(['push'], cwd=DASHBOARD_PATH)

            print("--- ✅ Dashboard Update Complete ---")

        except Exception as e:
            print(f"Error updating dashboard README: {e}", file=sys.stderr)

    def execute(self):
        print("--- 🚀 Starting Build Sequence ---")

        # 1) Pull top-level repo
        print("\n--- Pulling RAISIN_MASTER (Project Root) ---")
        pull_success = run_git_command(['pull'], cwd=self.working_dir)
        self.master_sha = get_local_branch_tip(PROJECT_ROOT, 'main')

        status_emoji = "✅ **Success**" if pull_success else "❌ **Failure**"
        self.results.append(("**RAISIN_MASTER**", status_emoji, self.master_sha, "git pull"))

        if not pull_success:
            print("RAISIN_MASTER pull failed. Aborting build sequence.", file=sys.stderr)
            return

        # 2) Git Pull Raion
        cmd = [sys.executable, str(RAISIN_SCRIPT), 'git', 'pull', 'raion']
        if not self._run_and_store(cmd, "**RAISIN**", self.master_sha, "git pull raion"):
            print("Command 'git pull raion' failed. Aborting.", file=sys.stderr)
            return

        # 3) Release Build
        cmd = [sys.executable, str(RAISIN_SCRIPT), 'build', 'release', 'install']
        if not self._run_and_store(cmd, "**GLOBAL**", self.master_sha, "build release install"):
            print("Build 'release install' failed. Aborting.", file=sys.stderr)
            return

        # 4) Release Release (Per-package)
        for package in self.package_names:
            if package == 'raisin_third_party_common':
                continue
            local_sha = get_local_package_commit_sha(package)
            cmd = [sys.executable, str(RAISIN_SCRIPT), 'release', package, 'release', '--yes']
            self._run_and_store(cmd, package, local_sha, "release release")

        # 5) Debug Build
        cmd = [sys.executable, str(RAISIN_SCRIPT), 'build', 'debug', 'install']
        if not self._run_and_store(cmd, "**GLOBAL**", self.master_sha, "build debug install"):
            print("Build 'debug install' failed. Aborting.", file=sys.stderr)
            return

        # 6) Debug Release (Per-package)
        for package in self.package_names:
            if package == 'raisin_third_party_common':
                continue
            local_sha = get_local_package_commit_sha(package)
            cmd = [sys.executable, str(RAISIN_SCRIPT), 'release', package, 'debug', '--yes']
            self._run_and_store(cmd, package, local_sha, "release debug")

        print("\n--- ✅ Build Sequence Finished ---")


# ------------- Repo list + check loop -------------

def load_repos(filename):
    """
    repositories.yaml example:
      raibo_controller:
        type: github
        url: "git@github.com:raionrobotics/raibo_controller_release.git"
    Returns { name: url_release, ... }
    """
    repo_map = {}
    try:
        with open(filename, 'r') as f:
            repos = yaml.safe_load(f)
            if not repos:
                return None
            for repo_name, details in repos.items():
                if details and details.get('type') == 'github' and 'url' in details:
                    repo_map[repo_name] = details['url']
    except FileNotFoundError:
        print(f"Error: Input file '{filename}' not found.", file=sys.stderr)
        return None
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}", file=sys.stderr)
        return None
    return repo_map if repo_map else None


def run_check():
    """
    Compares local SHAs vs remote SHAs on *source* repos (url without '_release'), branch 'main'.
    Triggers a build on the first mismatch.
    """
    print(f"Checking for new commits... (Source: {REPO_LIST_FILE.name})")

    repo_map = load_repos(REPO_LIST_FILE)
    if repo_map is None:
        print("Skipping this run due to config error.", file=sys.stderr)
        return

    trigger_build = False
    triggering_repo = ""

    for repo_name, url_release in repo_map.items():
        print(f"--- Checking: {repo_name}")

        local_sha = get_local_package_commit_sha(repo_name)
        remote_sha, source_url, ref_used, method = get_latest_commit_from_source_repo(url_release)

        print(f"  Release URL: {url_release}")
        print(f"  Source URL:  {source_url}")
        print(f"  Remote ref:  {ref_used} via {method}")
        print(f"  Local SHA:   {local_sha}")
        print(f"  Remote SHA:  {remote_sha}")

        if remote_sha is None:
            print("  Status: Could not get remote SHA from source repo. Skipping check for this repo.")
            continue

        if local_sha == "N/A":
            print("  Status: 🚨 CHANGE DETECTED! (Local repo not found) 🚨")
            trigger_build = True
            triggering_repo = repo_name
            break

        if local_sha != remote_sha:
            print("  Status: 🚨 CHANGE DETECTED! 🚨")
            trigger_build = True
            triggering_repo = repo_name
            break

    if trigger_build:
        print(f"\n✅ Done. Change found in '{triggering_repo}'. Triggering build process...")

        all_package_names = list(repo_map.keys())
        builder = BuildSequence(all_package_names)
        builder.execute()
        builder.report_all_to_dashboard()
    else:
        print("\n✅ Done. All repositories are in sync.")


# ------------- Main -------------

if __name__ == "__main__":
    print("--- Starting Commit Watcher ---")
    print(f"Loading repos from: {REPO_LIST_FILE}")
    ensure_dashboard_repo()
    print("Press Ctrl+C to stop.")

    try:
        while True:
            run_check()
            print(f"\n--- Waiting 10 seconds... ---")
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping watcher. Goodbye!")
        sys.exit(0)
