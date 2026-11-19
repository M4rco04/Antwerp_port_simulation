"""Shared infrastructure for the NxtPort Open Data collectors (src/data/*_collector.py).

Provides: .env loading, UTC logging with rotation, single-instance lock, crash-safe
JSON state, persistent daily call budget, OAuth2 token handling, a hardened HTTP
client, atomic file writers and the never-ending run loop with back-off.

Only dependency: requests
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[
    2
]  # <project>/src/data/opendata/opendata_common.py -> <project>

DEFAULT_TOKEN_URL = (
    "https://b2cnxtweuprd.b2clogin.com/b2cnxtweuprd.onmicrosoft.com/"
    "B2C_1A_SIGNUP_SIGNIN_IDENTITY/oauth2/v2.0/token"
)
DEFAULT_SCOPE = (
    "https://b2cnxtweuprd.onmicrosoft.com/4579a10e-8504-42a0-bedf-9f08eeacd456/.default"
)
DEFAULT_BASES = {
    "BRIDGESANDLOCKS": "https://api-bridgesandlocks.nxtport.com/v1",
    "METEO": "https://api-meteo.nxtport.com/v1",
    "PORTSTAYS": "https://api-portstays.nxtport.com/v1",
}
API_KEY_ENV = {
    "BRIDGESANDLOCKS": "BRIDGESANDLOCKS_API_KEY",
    "METEO": "METEO_API_KEY",
    "PORTSTAYS": "PORTSTAYS_API_KEY",
}
# The gateway answers "403 Forbidden" (HTML) to python-requests' default User-Agent.
DEFAULT_USER_AGENT = "Mozilla/5.0"


# --------------------------------------------------------------------------- errors
class CollectorError(Exception):
    """Base class for all expected, recoverable collector errors."""


class TransientError(CollectorError):
    """Network problem, timeout, 5xx, invalid JSON ... - retry later with back-off."""


class AuthError(CollectorError):
    """Token could not be obtained or the API rejected the token (401)."""


class BadRequest(CollectorError):
    """HTTP 400 - the request itself is wrong; retrying the same thing will not help."""


class RateLimited(CollectorError):
    """HTTP 403 (documented as 'too many requests') or 429."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class BudgetExhausted(CollectorError):
    """Own daily call budget used up - sleep until the next UTC day."""

    def __init__(self, message: str, wait_seconds: float):
        super().__init__(message)
        self.wait_seconds = wait_seconds


# --------------------------------------------------------------------------- helpers
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(moment: Optional[datetime] = None) -> str:
    """Sortable UTC stamp used in file names, e.g. 20261119T101500Z."""
    return (moment or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_hash(obj: Any) -> str:
    raw = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def as_list(data: Any) -> List[Any]:
    """Responses should be JSON arrays; tolerate a wrapping object."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def data_root() -> Path:
    return Path(
        os.environ.get("OPENDATA_DATA_DIR") or PROJECT_ROOT / "data" / "opendata"
    )


def load_env() -> None:
    """Load KEY=VALUE from .env (cwd, project root, script folder); real env vars win."""
    for path in (Path.cwd() / ".env", PROJECT_ROOT / ".env", HERE / ".env"):
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        except OSError:
            continue


def env_number(
    name: str, default, minimum=None, cast=int, log: Optional[logging.Logger] = None
):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        value = cast(raw)
    except ValueError:
        if log:
            log.warning("invalid value for %s=%r, using default %s", name, raw, default)
        return default
    if minimum is not None and value < minimum:
        if log:
            log.warning(
                "%s=%s is below the minimum %s, using the minimum", name, value, minimum
            )
        return minimum
    return value


def setup_logging(name: str) -> logging.Logger:
    log = logging.getLogger(f"opendata.{name}")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    formatter = logging.Formatter(
        f"%(asctime)sZ %(levelname)-8s [{name}] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    formatter.converter = time.gmtime  # log timestamps in UTC
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    log.addHandler(console)
    try:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / f"{name}_collector.log",
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except OSError as exc:
        log.warning("file logging disabled: %s", exc)
    return log


# --------------------------------------------------------------------------- files
def atomic_write(path: Path, text: str) -> None:
    """Write via temp file + os.replace so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(
            5
        ):  # Windows: antivirus/indexer may briefly lock the target
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def unique_path(directory: Path, prefix: str, extension: str) -> Path:
    stamp = utc_stamp()
    path = directory / f"{prefix}_{stamp}.{extension}"
    counter = 2
    while path.exists():
        path = directory / f"{prefix}_{stamp}_{counter}.{extension}"
        counter += 1
    return path


def write_json_snapshot(directory: Path, prefix: str, payload: Any) -> Path:
    path = unique_path(directory, prefix, "json")
    atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return path


def write_csv_snapshot(
    directory: Path, prefix: str, fieldnames: List[str], rows: List[Dict[str, Any]]
) -> Path:
    path = unique_path(directory, prefix, "csv")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buffer.getvalue())
    return path


class JsonState:
    """Small persistent dict. A corrupt file is moved aside instead of crashing the collector."""

    def __init__(self, path: Path, log: logging.Logger):
        self.path = path
        self.log = log
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            self.log.warning(
                "cannot read state file %s: %s (starting empty)", self.path, exc
            )
            return
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("state is not a JSON object")
            self.data = obj
        except ValueError as exc:
            backup = self.path.with_suffix(f".corrupt-{int(time.time())}")
            self.log.error(
                "state file corrupt (%s) - moved to %s, starting empty",
                exc,
                backup.name,
            )
            try:
                os.replace(self.path, backup)
            except OSError:
                pass

    def save(self) -> None:
        try:
            atomic_write(self.path, json.dumps(self.data, indent=1, ensure_ascii=False))
        except OSError as exc:
            self.log.error("cannot save state file %s: %s", self.path, exc)


class SingleInstance:
    """OS-level lock so two copies cannot run (they would double the API calls)."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+")
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


class DailyBudget:
    """Persistent per-UTC-day call counter (survives restarts)."""

    def __init__(self, state: JsonState, cap: int):
        self.state = state
        self.cap = cap

    def _today(self) -> Dict[str, Any]:
        day = utc_now().strftime("%Y-%m-%d")
        budget = self.state.data.setdefault("budget", {})
        if budget.get("day") != day:
            budget["day"] = day
            budget["calls"] = 0
        return budget

    @property
    def calls_today(self) -> int:
        return int(self._today().get("calls", 0))

    def check(self) -> None:
        if self.cap <= 0:
            return
        if self.calls_today >= self.cap:
            now = utc_now()
            reset = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=30, microsecond=0
            )
            raise BudgetExhausted(
                f"daily budget of {self.cap} calls used up",
                (reset - now).total_seconds(),
            )

    def register(self) -> None:
        budget = self._today()
        budget["calls"] = int(budget.get("calls", 0)) + 1
        self.state.save()


# --------------------------------------------------------------------------- HTTP
def _snippet(response: requests.Response, limit: int = 200) -> str:
    return " ".join(response.text[:limit].split())


def _retry_after(response: requests.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return min(max(float(raw), 0.0), 6 * 3600.0)
    except ValueError:
        return None


class TokenProvider:
    SAFETY_SECONDS = 120

    def __init__(self, session: requests.Session, log: logging.Logger):
        self.session = session
        self.log = log
        self.token: Optional[str] = None
        self.expires_at = 0.0

    def get(self, force: bool = False) -> str:
        if (
            not force
            and self.token
            and time.time() < self.expires_at - self.SAFETY_SECONDS
        ):
            return self.token
        return self._fetch()

    def _fetch(self) -> str:
        url = os.environ.get("NXTPORT_TOKEN_URL") or DEFAULT_TOKEN_URL
        scope = os.environ.get("NXTPORT_SCOPE") or DEFAULT_SCOPE
        try:
            response = self.session.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": os.environ["NXTPORT_CLIENT_ID"],
                    "client_secret": os.environ["NXTPORT_CLIENT_SECRET"],
                    "scope": scope,
                },
                timeout=(10, 30),
            )
        except requests.RequestException as exc:
            raise TransientError(f"token request failed: {exc}") from exc

        try:
            body = response.json()
            if not isinstance(body, dict):
                body = {}
        except ValueError:
            body = {}

        if response.status_code == 200 and body.get("access_token"):
            try:
                ttl = float(body.get("expires_in", 3600))
            except (TypeError, ValueError):
                ttl = 3600.0
            self.token = str(body["access_token"])
            self.expires_at = time.time() + ttl
            self.log.info("new access token obtained (valid %.0f s)", ttl)
            return self.token

        detail = (
            body.get("error_description") or body.get("error") or _snippet(response)
        )
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise TransientError(
                f"token endpoint HTTP {response.status_code}: {detail}"
            )
        raise AuthError(
            f"token request rejected (HTTP {response.status_code}): {detail}"
        )


class NxtPortClient:
    def __init__(
        self, api: str, log: logging.Logger, budget: Optional[DailyBudget] = None
    ):
        self.api = api
        self.log = log
        self.budget = budget
        self.base = (os.environ.get(f"{api}_BASE_URL") or DEFAULT_BASES[api]).rstrip(
            "/"
        )
        self.api_key = os.environ[API_KEY_ENV[api]]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": os.environ.get("NXTPORT_USER_AGENT")
                or DEFAULT_USER_AGENT,
                "Accept": "application/json",
            }
        )
        self.tokens = TokenProvider(self.session, log)

    def _count(self) -> None:
        if self.budget:
            self.budget.register()

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.base + path
        if self.budget:
            self.budget.check()

        response = None
        for attempt in (0, 1):
            token = self.tokens.get(force=(attempt == 1))
            headers = {
                "Authorization": f"Bearer {token}",
                "Ocp-Apim-Subscription-Key": self.api_key,
            }
            try:
                response = self.session.get(
                    url, headers=headers, params=params, timeout=(10, 45)
                )
            except requests.ReadTimeout as exc:
                self._count()  # request probably reached the server
                raise TransientError(f"read timeout for {url}: {exc}") from exc
            except requests.RequestException as exc:
                raise TransientError(f"network error for {url}: {exc}") from exc
            self._count()
            if response.status_code == 401 and attempt == 0:
                self.log.warning("HTTP 401 - refreshing token and retrying once")
                continue
            break

        code = response.status_code
        if code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise TransientError(
                    f"HTTP 200 but body is not valid JSON: {_snippet(response)}"
                ) from exc
        if code in (403, 429):
            raise RateLimited(
                f"HTTP {code} from {url}: {_snippet(response)} (docs: 'too many requests'; an HTML "
                "gateway page instead of JSON can also mean a blocked User-Agent/IP)",
                _retry_after(response),
            )
        if code == 401:
            raise AuthError(f"HTTP 401 even with a fresh token: {_snippet(response)}")
        if code == 400:
            raise BadRequest(
                f"HTTP 400 from {url} params={params}: {_snippet(response)}"
            )
        if code in (408, 425) or code >= 500:
            raise TransientError(f"HTTP {code} from {url}: {_snippet(response)}")
        raise TransientError(f"unexpected HTTP {code} from {url}: {_snippet(response)}")


# --------------------------------------------------------------------------- runtime
def _backoff(failures: int, base: float, cap: float) -> float:
    return min(cap, base * (2 ** max(0, failures - 1)))


class Runtime:
    def __init__(
        self,
        name: str,
        api: str,
        interval: int,
        cap: int,
        log: logging.Logger,
        state: JsonState,
        lock: SingleInstance,
    ):
        self.name = name
        self.api = api
        self.interval = interval
        self.log = log
        self.state = state
        self.lock = lock
        self.out_dir = data_root() / name
        self.out_label = str(self.out_dir)  # shown in the start-up log
        self.budget = DailyBudget(state, cap)
        self.client = NxtPortClient(api, log, self.budget)
        self.stop = threading.Event()
        self.backoff_base = env_number("OPENDATA_BACKOFF_BASE", 30.0, 1.0, float, log)
        self.backoff_max = env_number("OPENDATA_BACKOFF_MAX", 1800.0, 1.0, float, log)
        self.rate_min = env_number("OPENDATA_RATE_LIMIT_MIN", 900.0, 1.0, float, log)
        self.rate_max = env_number("OPENDATA_RATE_LIMIT_MAX", 7200.0, 1.0, float, log)
        self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            self.log.info("signal %s received - shutting down", signum)
            self.stop.set()

        for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, sig_name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep (1 s slices so Ctrl+C / SIGTERM work everywhere)."""
        end = time.monotonic() + seconds
        while not self.stop.is_set():
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            self.stop.wait(min(1.0, remaining))

    def _respect_min_spacing(self) -> None:
        """After a restart, do not call earlier than one interval after the last attempt."""
        last = self.state.data.get("last_attempt_epoch")
        if not isinstance(last, (int, float)):
            return
        remaining = self.interval - (time.time() - last)
        if 0 < remaining <= self.interval:
            self.log.info(
                "restart detected - waiting %.0f s to keep the polling interval",
                remaining,
            )
            self.sleep(remaining)

    def run(self, cycle: Callable[[], None]) -> None:
        self.log.info(
            "started: interval=%ss, daily cap=%s (calls today: %s), output=%s",
            self.interval,
            self.budget.cap or "none",
            self.budget.calls_today,
            self.out_label,
        )
        if self.budget.cap and 86400 / self.interval > self.budget.cap:
            self.log.warning(
                "interval %ss would need %.0f calls/day but the cap is %s - the collector will "
                "pause when the cap is reached",
                self.interval,
                86400 / self.interval,
                self.budget.cap,
            )
        self._respect_min_spacing()

        failures = 0
        while not self.stop.is_set():
            started = time.monotonic()
            self.state.data["last_attempt_epoch"] = time.time()
            delay: Optional[float] = None
            try:
                cycle()
                failures = 0
            except BudgetExhausted as exc:
                delay = exc.wait_seconds
                self.log.warning(
                    "%s - sleeping %.0f s until the next UTC day", exc, delay
                )
            except RateLimited as exc:
                failures += 1
                delay = max(
                    _backoff(failures, self.rate_min, self.rate_max),
                    exc.retry_after or 0.0,
                )
                self.log.warning(
                    "%s -> pausing %.0f s (failure #%d). If this repeats, increase %s_INTERVAL_SECONDS.",
                    exc,
                    delay,
                    failures,
                    self.api,
                )
            except BadRequest as exc:
                self.log.error("%s (will retry at the normal interval)", exc)
            except (TransientError, AuthError) as exc:
                failures += 1
                delay = _backoff(failures, self.backoff_base, self.backoff_max)
                self.log.warning(
                    "%s -> retry in %.0f s (failure #%d)", exc, delay, failures
                )
            except OSError as exc:  # disk full, permission denied, ...
                failures += 1
                delay = _backoff(failures, self.backoff_base, self.backoff_max)
                self.log.error(
                    "file system error: %s -> retry in %.0f s (failure #%d)",
                    exc,
                    delay,
                    failures,
                )
            except Exception:  # noqa: BLE001 - the collector must never die
                failures += 1
                delay = _backoff(failures, self.backoff_base, self.backoff_max)
                self.log.exception(
                    "unexpected error -> retry in %.0f s (failure #%d)", delay, failures
                )

            self.state.save()
            if delay is None:
                delay = max(1.0, self.interval - (time.monotonic() - started))
            delay += random.uniform(0, min(10.0, delay * 0.05))
            self.log.info("next run in %.0f s", delay)
            self.sleep(delay)
        self.log.info("stopped")


def start(name: str, api: str, default_interval: int, default_cap: int = 0) -> Runtime:
    """Common start-up: env, logging, config validation, single-instance lock, state."""
    load_env()
    log = setup_logging(name)

    required = ["NXTPORT_CLIENT_ID", "NXTPORT_CLIENT_SECRET", API_KEY_ENV[api]]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        log.critical(
            "missing required settings: %s (put them in .env)", ", ".join(missing)
        )
        sys.exit(2)

    state_dir = data_root() / "_state"
    lock = SingleInstance(state_dir / f"{name}.lock")
    if not lock.acquire():
        log.critical("another %s collector instance is already running - exiting", name)
        sys.exit(3)

    interval = env_number(f"{api}_INTERVAL_SECONDS", default_interval, 5, int, log)
    cap = env_number(f"{api}_DAILY_CAP", default_cap, 0, int, log)
    state = JsonState(state_dir / f"{name}.json", log)
    return Runtime(name, api, interval, cap, log, state, lock)
