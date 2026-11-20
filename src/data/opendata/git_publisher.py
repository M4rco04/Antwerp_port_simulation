"""Git publisher - pushes newly collected Open Data files to the `opendata` branch.

Run (from the project root):  python src/data/opendata/git_publisher.py

How it works
  * It does NOT touch your working tree, index or current branch. It keeps its own clone in
    ./.opendata_repo (added to .git/info/exclude of the project) holding the branch `opendata`.
    The clone is partial + sparse: only the folder data/opendata is downloaded and checked out,
    the rest of the project never lands on disk there.
  * ONLY data/opendata/** is ever committed (enforced: the index is reset before every commit and
    the commit is refused if anything else is staged). Nothing else is ever pushed.
  * If the branch does not exist on the remote yet, it is created from the remote's default
    branch (not as an orphan), so it shares history with main and merging it later is clean.
  * Every cycle: fetch -> rebase on the remote branch if needed -> copy files that are not yet
    in the clone -> one commit -> push. Files are mirrored as data/opendata/<dataset>/<file>, so
    they can be pulled into the main tree with:  git checkout opendata -- data/opendata
  * Collector files are written atomically and never modified, so "not yet in the clone" means
    "not yet published". Nothing is ever sent twice, a failed push is simply retried.
  * Credentials come from your normal git setup (credential manager / SSH key / token in the
    remote URL). Prompts are disabled so the script can never hang waiting for input.

Settings (.env), all optional:
  OPENDATA_GIT_INTERVAL_SECONDS  default 3600   how often to publish
  OPENDATA_GIT_BRANCH            default opendata
  OPENDATA_GIT_BASE_BRANCH       default: remote default branch / main / master (only used when the
                                 branch does not exist yet)
  OPENDATA_GIT_REMOTE            default: URL of `origin` of the project repository
  OPENDATA_GIT_REPO_DIR          default ./.opendata_repo
  OPENDATA_GIT_DATASETS          default meteo,bridges,locks,port_stays
  OPENDATA_GIT_MAX_FILES         default 5000   files per commit (the rest follows right after)
  OPENDATA_GIT_USER_NAME / OPENDATA_GIT_USER_EMAIL   commit identity if git has none configured
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import opendata_common as oc
except ImportError:  # started as a package: python -m src.data.opendata.git_publisher
    from . import opendata_common as oc

NAME = "git_publisher"
ENV_PREFIX = "OPENDATA_GIT"
DEFAULT_INTERVAL = 3600
DEFAULT_BRANCH = "opendata"
DEFAULT_DATASETS = "meteo,bridges,locks,port_stays"
GIT_TIMEOUT = 300  # seconds, local/fast commands
NET_TIMEOUT = 900  # seconds, fetch / clone / push
EXTENSIONS = {".csv", ".json"}
MAX_FILE_BYTES = 90 * 1024 * 1024  # GitHub rejects files > 100 MB
AUTH_HINTS = (
    "Authentication failed",
    "Permission denied",
    "could not read Username",
    "terminal prompts disabled",
    "Invalid username or password",
    "HTTP 403",
    "access denied",
)


class GitError(oc.TransientError):
    """A git command failed - retried with back-off by the run loop."""


def redact(text: str) -> str:
    """Hide credentials embedded in URLs (https://user:token@host/...)."""
    return re.sub(r"(://)[^/@\s]+@", r"\1***@", text)


class Publisher:
    def __init__(self, rt: "oc.Runtime"):
        self.rt = rt
        self.log = rt.log
        self.branch = os.environ.get("OPENDATA_GIT_BRANCH") or DEFAULT_BRANCH
        self.repo = Path(
            os.environ.get("OPENDATA_GIT_REPO_DIR")
            or oc.PROJECT_ROOT / ".opendata_repo"
        ).resolve()
        self.datasets = [
            d.strip()
            for d in (
                os.environ.get("OPENDATA_GIT_DATASETS") or DEFAULT_DATASETS
            ).split(",")
            if d.strip()
        ]
        self.max_files = oc.env_number("OPENDATA_GIT_MAX_FILES", 5000, 1, int, self.log)
        self.env = dict(
            os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", LC_ALL="C"
        )
        self.env.setdefault(
            "GIT_SSH_COMMAND", "ssh -o BatchMode=yes"
        )  # never wait for an SSH passphrase
        self._warned_big: set = set()
        self._configured = False
        self.more_pending = False

        self._check_git_installed()
        self.remote = self._resolve_remote()
        self.log.info(
            "branch=%s remote=%s clone=%s datasets=%s",
            self.branch,
            redact(self.remote),
            self.repo,
            ",".join(self.datasets),
        )

    # ----------------------------------------------------------------- git plumbing
    def git(
        self,
        args,
        cwd: Optional[Path] = None,
        timeout: int = GIT_TIMEOUT,
        check: bool = True,
    ):
        try:
            proc = subprocess.run(
                ["git"] + list(args),
                cwd=str(cwd or self.repo),
                env=self.env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {args[0]} timed out after {timeout}s") from exc
        except OSError as exc:
            raise GitError(f"cannot run git {args[0]}: {exc}") from exc
        if check and proc.returncode != 0:
            raise GitError(self._explain(args, proc))
        return proc

    @staticmethod
    def _explain(args, proc) -> str:
        detail = redact((proc.stderr or proc.stdout or "").strip())[-500:]
        message = (
            f"git {args[0]} failed (exit {proc.returncode}): {' '.join(detail.split())}"
        )
        if any(hint.lower() in detail.lower() for hint in AUTH_HINTS):
            message += " -> check credentials (credential helper / SSH key / token) for the remote"
        return message

    def _check_git_installed(self) -> None:
        try:
            subprocess.run(
                ["git", "--version"], capture_output=True, timeout=30, check=True
            )
        except (OSError, subprocess.SubprocessError):
            self.log.critical("git is not installed or not on PATH")
            sys.exit(2)

    def _resolve_remote(self) -> str:
        remote = os.environ.get("OPENDATA_GIT_REMOTE")
        if remote:
            return remote
        try:
            proc = subprocess.run(
                ["git", "-C", str(oc.PROJECT_ROOT), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        self.log.critical(
            "no git remote: set OPENDATA_GIT_REMOTE in .env or add an 'origin' to the project repo"
        )
        sys.exit(2)

    def has_head(self) -> bool:
        return (
            self.git(["rev-parse", "--verify", "-q", "HEAD"], check=False).returncode
            == 0
        )

    def counts(self) -> Optional[Tuple[int, int]]:
        """(commits ahead of origin/<branch>, commits behind) or None when it cannot be computed."""
        proc = self.git(
            [
                "rev-list",
                "--left-right",
                "--count",
                f"HEAD...refs/remotes/origin/{self.branch}",
            ],
            check=False,
        )
        if proc.returncode != 0:
            return None
        parts = proc.stdout.split()
        return (int(parts[0]), int(parts[1])) if len(parts) == 2 else None

    # ----------------------------------------------------------------- repository setup
    def ensure_repo(self) -> None:
        if not (self.repo / ".git").exists():
            if self.repo.exists() and any(self.repo.iterdir()):
                raise GitError(
                    f"{self.repo} exists, is not empty and is not a git repository - "
                    "move it or set OPENDATA_GIT_REPO_DIR"
                )
            self._configured = False
            heads = self.git(
                ["ls-remote", "--heads", self.remote, self.branch],
                cwd=oc.PROJECT_ROOT,
                timeout=120,
            ).stdout
            remote_has_branch = any(
                line.strip().endswith(f"refs/heads/{self.branch}")
                for line in heads.splitlines()
            )
            self.repo.parent.mkdir(parents=True, exist_ok=True)
            # --no-checkout + blob filter + sparse checkout: only data/opendata is ever downloaded/checked out
            clone = ["clone", "--no-checkout", "--single-branch", "--filter=blob:none"]
            if remote_has_branch:
                self.log.info(
                    "cloning existing branch '%s' into %s (data folder only)",
                    self.branch,
                    self.repo,
                )
                self.git(
                    clone + ["--branch", self.branch, self.remote, str(self.repo)],
                    cwd=oc.PROJECT_ROOT,
                    timeout=NET_TIMEOUT,
                )
                self._sparse_checkout()
                self.git(["checkout", "-q", self.branch])
            else:
                base = self._base_branch()
                if not base:
                    raise GitError(
                        "branch '%s' does not exist on the remote and no base branch (main/master) "
                        "was found - create it first or set OPENDATA_GIT_BASE_BRANCH"
                        % self.branch
                    )
                self.log.info(
                    "branch '%s' does not exist on the remote yet - creating it from '%s'",
                    self.branch,
                    base,
                )
                self.git(
                    clone + ["--branch", base, self.remote, str(self.repo)],
                    cwd=oc.PROJECT_ROOT,
                    timeout=NET_TIMEOUT,
                )
                self._sparse_checkout()
                self.git(["checkout", "-q", "-b", self.branch])
            self._exclude_clone_from_project()
        if not self._configured:
            self._configure()

    def _base_branch(self) -> Optional[str]:
        """Branch to start a missing `opendata` branch from: OPENDATA_GIT_BASE_BRANCH, the remote's
        default branch, then main, then master (whichever really exists)."""
        heads_out = self.git(
            ["ls-remote", "--heads", self.remote], cwd=oc.PROJECT_ROOT, timeout=120
        ).stdout
        heads = {
            line.split("refs/heads/", 1)[1].strip()
            for line in heads_out.splitlines()
            if "refs/heads/" in line
        }
        candidates = [os.environ.get("OPENDATA_GIT_BASE_BRANCH")]
        symref = self.git(
            ["ls-remote", "--symref", self.remote, "HEAD"],
            cwd=oc.PROJECT_ROOT,
            timeout=120,
            check=False,
        ).stdout
        for line in symref.splitlines():
            if line.startswith("ref:") and "refs/heads/" in line:
                candidates.append(line.split("refs/heads/", 1)[1].split()[0])
        candidates += ["main", "master"]
        return next((name for name in candidates if name and name in heads), None)

    def _sparse_checkout(self) -> None:
        """Restrict the clone's working tree to data/opendata."""
        proc = self.git(
            ["sparse-checkout", "set", "--cone", "data/opendata"], check=False
        )
        if proc.returncode != 0:  # git < 2.35
            self.git(["sparse-checkout", "init", "--cone"])
            self.git(["sparse-checkout", "set", "data/opendata"])

    def _exclude_clone_from_project(self) -> None:
        """Keep the clone out of `git status` of the main project (local, not committed)."""
        try:
            relative = self.repo.relative_to(oc.PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            return
        exclude = oc.PROJECT_ROOT / ".git" / "info" / "exclude"
        try:
            if exclude.parent.is_dir():
                line = f"/{relative}/"
                existing = (
                    exclude.read_text(encoding="utf-8") if exclude.exists() else ""
                )
                if line not in existing.splitlines():
                    with open(exclude, "a", encoding="utf-8") as fh:
                        fh.write(
                            ("" if existing.endswith("\n") or not existing else "\n")
                            + line
                            + "\n"
                        )
        except OSError:
            pass

    def _configure(self) -> None:
        current = self.git(
            ["symbolic-ref", "--short", "HEAD"], check=False
        ).stdout.strip()
        if current and current != self.branch:
            raise GitError(
                f"clone {self.repo} is on branch '{current}', expected '{self.branch}'"
            )
        self.git(
            ["config", "core.autocrlf", "false"]
        )  # keep CSV/JSON byte-identical on Windows
        if (
            self.has_head()
            and self.git(
                ["config", "--get", "core.sparseCheckout"], check=False
            ).stdout.strip()
            != "true"
        ):
            self._sparse_checkout()
        if not self.git(["config", "user.email"], check=False).stdout.strip():
            self.git(
                [
                    "config",
                    "user.email",
                    os.environ.get("OPENDATA_GIT_USER_EMAIL")
                    or "opendata-bot@users.noreply.github.com",
                ]
            )
        if not self.git(["config", "user.name"], check=False).stdout.strip():
            self.git(
                [
                    "config",
                    "user.name",
                    os.environ.get("OPENDATA_GIT_USER_NAME") or "opendata-bot",
                ]
            )
        url = self.git(["remote", "get-url", "origin"], check=False)
        if url.returncode != 0:
            self.git(["remote", "add", "origin", self.remote])
        elif url.stdout.strip() != self.remote:
            self.git(["remote", "set-url", "origin", self.remote])
        try:  # half-copied temp files must never be committed
            info = self.repo / ".git" / "info"
            info.mkdir(parents=True, exist_ok=True)
            exclude = info / "exclude"
            existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            if "*.tmp" not in existing.splitlines():
                with open(exclude, "a", encoding="utf-8") as fh:
                    fh.write(
                        ("" if existing.endswith("\n") or not existing else "\n")
                        + "*.tmp\n"
                    )
        except OSError:
            pass
        self._configured = True

    def clear_stale_lock(self) -> None:
        """A git process killed by a timeout can leave .git/index.lock behind (we are the only user)."""
        lock = self.repo / ".git" / "index.lock"
        try:
            if lock.exists() and time.time() - lock.stat().st_mtime > 120:
                lock.unlink()
                self.log.warning("removed stale %s", lock)
        except OSError:
            pass

    # ----------------------------------------------------------------- sync steps
    def fetch(self) -> bool:
        """Fetch the remote branch. Returns False when it does not exist on the remote (yet)."""
        proc = self.git(
            [
                "fetch",
                "origin",
                f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}",
            ],
            timeout=NET_TIMEOUT,
            check=False,
        )
        if proc.returncode == 0:
            return True
        if "couldn't find remote ref" in (proc.stderr or ""):
            return False
        raise GitError(self._explain(["fetch"], proc))

    def integrate(self, remote_exists: bool) -> None:
        """Bring the local branch on top of origin/<branch> (only needed when someone else pushed)."""
        if not remote_exists:
            return
        remote_ref = f"refs/remotes/origin/{self.branch}"
        if not self.has_head():
            self.git(["checkout", "-q", "-B", self.branch, remote_ref])
            return
        counts = self.counts()
        if counts and counts[1] > 0:
            proc = self.git(["rebase", remote_ref], check=False)
            if proc.returncode != 0:
                self.git(["rebase", "--abort"], check=False)
                raise GitError(self._explain(["rebase"], proc))
            self.log.info("rebased on %d new remote commit(s)", counts[1])

    def remove_temp_files(self) -> None:
        """Delete half-copied *.tmp files from an interrupted run (they must never be committed)."""
        target_root = self.repo / "data" / "opendata"
        if not target_root.is_dir():
            return
        for temp in target_root.rglob("*.tmp"):
            try:
                temp.unlink()
            except OSError:
                pass

    def commit_if_dirty(self, message: str) -> int:
        """Commit new/changed files under data/opendata - and nothing else. Returns the file count.

        The index is reset to HEAD first, then only data/opendata is staged. `add -f` is deliberate:
        the branch may carry a .gitignore (e.g. copied from main) that ignores data/. As a last
        line of defence the commit is refused if any path outside data/opendata is staged.
        """
        self.git(["reset", "-q"], check=False)
        if (self.repo / "data" / "opendata").is_dir():
            self.git(["add", "-f", "-A", "--", "data/opendata"])
        staged = [
            line.strip()
            for line in self.git(
                ["diff", "--cached", "--name-only"]
            ).stdout.splitlines()
            if line.strip()
        ]
        outside = [path for path in staged if not path.startswith("data/opendata/")]
        if outside:
            self.git(["reset", "-q"], check=False)
            raise GitError(
                f"refusing to commit paths outside data/opendata: {outside[:3]}"
            )
        if not staged:
            return 0
        self.git(["commit", "-q", "-m", message])
        return len(staged)

    def push_if_needed(self) -> bool:
        counts = self.counts()
        ahead = counts[0] if counts is not None else (1 if self.has_head() else 0)
        if ahead == 0:
            return False
        for attempt in (1, 2):
            proc = self.git(
                ["push", "-q", "-u", "origin", f"HEAD:refs/heads/{self.branch}"],
                timeout=NET_TIMEOUT,
                check=False,
            )
            if proc.returncode == 0:
                self.log.info(
                    "pushed %d commit(s) to %s/%s", ahead, "origin", self.branch
                )
                return True
            err = proc.stderr or ""
            if attempt == 1 and any(
                s in err
                for s in ("rejected", "non-fast-forward", "fetch first", "stale info")
            ):
                self.log.warning(
                    "push rejected (remote has new commits) - rebasing and retrying once"
                )
                self.integrate(self.fetch())
                continue
            raise GitError(self._explain(["push"], proc))
        return False

    # ----------------------------------------------------------------- copying files
    def copy_new_files(self) -> Dict[str, int]:
        """Copy collector files that are not yet in the clone. Returns {dataset: count}."""
        source_root = oc.data_root()
        target_root = self.repo / "data" / "opendata"
        copied: Dict[str, int] = {}
        total = 0
        self.more_pending = False

        for dataset in self.datasets:
            source_dir = source_root / dataset
            if not source_dir.is_dir():
                continue
            try:
                names = sorted(os.listdir(source_dir))
            except OSError as exc:
                self.log.warning("cannot list %s: %s", source_dir, exc)
                continue
            for name in names:
                if name.startswith(".") or Path(name).suffix.lower() not in EXTENSIONS:
                    continue
                source = source_dir / name
                target = target_root / dataset / name
                if target.exists():
                    continue
                if total >= self.max_files:
                    self.more_pending = True
                    return copied
                try:
                    if not source.is_file():
                        continue
                    size = source.stat().st_size
                    if size > MAX_FILE_BYTES:
                        if source not in self._warned_big:
                            self._warned_big.add(source)
                            self.log.warning(
                                "skipping %s (%.0f MB > GitHub's file size limit)",
                                source,
                                size / 1e6,
                            )
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_name(target.name + ".tmp")
                    shutil.copyfile(source, temp)
                    os.replace(temp, target)
                except (
                    OSError
                ) as exc:  # one locked/unreadable file must not block the rest
                    self.log.warning(
                        "cannot copy %s: %s (will retry next cycle)", source, exc
                    )
                    continue
                copied[dataset] = copied.get(dataset, 0) + 1
                total += 1
        return copied

    # ----------------------------------------------------------------- one cycle
    def cycle(self) -> None:
        self.clear_stale_lock()
        self.ensure_repo()
        self.remove_temp_files()
        remote_exists = self.fetch()
        if self.commit_if_dirty(
            "opendata: recover files left uncommitted by an interrupted run"
        ):
            self.log.warning("committed files left over from an interrupted run")
        self.integrate(remote_exists)

        pushed_any = False
        any_copied = False
        while not self.rt.stop.is_set():
            copied = self.copy_new_files()
            if copied:
                any_copied = True
                summary = ", ".join(f"{k}: {v}" for k, v in sorted(copied.items()))
                total = sum(copied.values())
                self.commit_if_dirty(
                    f"opendata: add {total} files ({summary}) {oc.iso_z(oc.utc_now())}"
                )
                self.log.info("committed %d new files (%s)", total, summary)
            if self.push_if_needed():
                pushed_any = True
            if not self.more_pending:
                break
            self.log.info("more files pending - continuing with the next batch")
            self.rt.sleep(5)
        if not pushed_any and not any_copied:
            self.log.info("nothing new to publish")


def main() -> None:
    rt = oc.start(NAME, None, DEFAULT_INTERVAL, env_prefix=ENV_PREFIX)
    publisher = Publisher(rt)
    rt.out_label = str(publisher.repo)
    rt.run(publisher.cycle)


if __name__ == "__main__":
    main()
