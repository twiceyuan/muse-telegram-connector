#!/usr/bin/env python3
"""Resident Telegram listener (zero-LLM polling daemon).

An alternative to the agent-driven watch.py slices: this process
loops on getUpdates long polling itself, applies the exact same
relevance/drop rules as fetch.py (by importing it), appends records
to queue.jsonl, advances the offset only after records are durable
on disk, and fires the same read-receipt / typing / stuck-watchdog
side signals. An agent is then needed only to reply to queued
records, and to revive this process when it dies.

Credential model: identical to fetch.py. Every getUpdates call goes
through the connector's tg.call, which fetches a fresh credential
surrogate per request; no token is ever present in this process.
The process must therefore be launched from inside an agent turn
(detached), exactly like typing_keeper.py. It does not survive VM /
runtime replacements, so pair it with a lightweight supervisor (a
hook or a scheduled task) that watches the heartbeat file below and
relaunches it from an agent turn when the heartbeat goes stale.
Message loss is still bounded by the offset discipline: the offset
advances only after queue records are fsynced, and Telegram keeps
unconfirmed updates for about 24 hours.

Interlocks:
- listener.lock: single instance; a second copy exits at once.
- watch.lock (the legacy watch.py lock): held for the listener's
  whole lifetime, so any legacy watcher slice prints LOCKED and
  stands down instead of double-pulling.
- listener.stop: if this file exists the listener exits at the next
  loop boundary and supervisors must not revive it (rollback /
  maintenance switch).

State: listener-state.json {"started_at", "beat_at", "last_ok_at",
"pid", "cycles", "errors"} written atomically after every cycle.
beat_at proves the process is alive; last_ok_at proves the API path
is healthy. Logs go to listener.log in the relay directory.
"""
import fcntl
import json
import os
import sys
import time

BASE = os.environ.get(
    "TG_RELAY_DIR", os.path.expanduser("~/workspace/telegram-relay"))
sys.path.insert(0, BASE)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import fetch as relay  # noqa: E402  (fetch.py: rules, offset, tg, paths)

STATE = os.path.join(BASE, "listener-state.json")
LOG = os.path.join(BASE, "listener.log")
STOP = os.path.join(BASE, "listener.stop")
POLL_TIMEOUT = 50          # server-side long-poll seconds per call
HTTP_TIMEOUT = 75          # client timeout must exceed the poll
BACKOFF_START = 5
BACKOFF_MAX = 60


def log(msg: str) -> None:
    # Fixed Asia/Shanghai rendering: the launching agent's environment
    # TZ varies (CST vs UTC), which made log lines flip timezones.
    stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                          time.gmtime(time.time() + 8 * 3600))
    line = "%s %s" % (stamp, msg)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        # A broken stdout must never kill the daemon (Codex review).
        pass


def write_state(state: dict) -> None:
    tmp = "%s.%d.tmp" % (STATE, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE)


def safe_write_state(state: dict) -> None:
    """Heartbeat writes must not kill the loop on a transient disk
    error; a stale heartbeat gets the process revived anyway, which
    is strictly better than dying mid-retry (Codex review)."""
    try:
        write_state(state)
    except Exception:
        pass


def fsync_path(path: str) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def process_updates(updates) -> int:
    """Same handling as fetch.main: queue everything not dropped and
    advance the offset only after the queue write is durable; side
    signals (read receipt, typing, watchdog) fire after the offset is
    committed, best-effort. A single malformed update is logged and
    skipped so it cannot wedge the stream behind it (Codex review).
    Returns the number of relevant records."""
    offset = relay.load_offset()
    relevant_records = []
    max_id = offset - 1
    with open(relay.QUEUE, "a", encoding="utf-8") as qf:
        for update in updates:
            try:
                uid = int(update.get("update_id", 0))
            except Exception:
                log("skipping update with unparseable id: %r" % (update,))
                continue
            max_id = max(max_id, uid)
            try:
                record = relay.compact(update)
                if relay.is_dropped(record):
                    try:
                        with open(relay.DROPPED, "a",
                                  encoding="utf-8") as df:
                            df.write(json.dumps(
                                record, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                    continue
                qf.write(json.dumps(record, ensure_ascii=False) + "\n")
                if relay.is_relevant(record):
                    relevant_records.append(record)
            except Exception:
                log("skipping malformed update %d:\n%s" % (
                    uid, __import__("traceback").format_exc()))
        qf.flush()
        os.fsync(qf.fileno())
    if updates:
        relay.save_offset(max_id + 1)
        fsync_path(relay.STATE)
    for record in relevant_records:
        relay.mark_read(record)
        relay.signal_typing(record)
        relay.signal_watchdog(record)
    return len(relevant_records)


def grab_lock(name: str, wait_secs: int = 0):
    """flock BASE/name exclusively; returns the open file or None.
    With wait_secs > 0, retries until the deadline before giving up."""
    fh = open(os.path.join(BASE, name), "w")
    deadline = time.time() + wait_secs
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.time() >= deadline:
                fh.close()
                return None
            time.sleep(2)


def main() -> int:
    os.makedirs(BASE, exist_ok=True)
    # The lock handles must stay referenced for the process's whole
    # lifetime: an unreferenced file object is closed by the GC, which
    # silently releases the flock.
    listener_lock = grab_lock("listener.lock")
    if listener_lock is None:
        log("another listener already holds listener.lock; exit")
        return 0
    watch_lock = grab_lock("watch.lock", wait_secs=120)
    if watch_lock is None:
        log("watch.lock still held after 120s; exit (supervisor retries)")
        return 1
    started = int(time.time())
    state = {"started_at": started, "beat_at": started, "last_ok_at": 0,
             "pid": os.getpid(), "cycles": 0, "errors": 0}
    safe_write_state(state)
    log("listener started pid=%d" % os.getpid())
    backoff = BACKOFF_START
    while not os.path.exists(STOP):
        cycle_start = time.time()
        try:
            result = relay.tg.call("getUpdates", {
                "offset": relay.load_offset(),
                "timeout": POLL_TIMEOUT,
                "limit": 100,
                "allowed_updates": ["message", "edited_message",
                                    "my_chat_member"],
            }, http_timeout=HTTP_TIMEOUT)
        except Exception as exc:  # network / credential layer hiccup
            result = {"ok": False, "description": "exception: %r" % (exc,)}
        if not isinstance(result, dict):
            result = {"ok": False,
                      "description": "non-dict result: %r" % (result,)}
        now = int(time.time())
        state["beat_at"] = now
        if result.get("ok"):
            state["last_ok_at"] = now
            state["cycles"] += 1
            try:
                n = process_updates(result.get("result", []))
            except Exception:
                # Batch-level processing failure: back off like an API
                # failure instead of spinning at 1/s (Codex review).
                state["errors"] += 1
                safe_write_state(state)
                log("process_updates failed; backoff %ss:\n%s" % (
                    backoff, __import__("traceback").format_exc()))
                time.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue
            backoff = BACKOFF_START
            if n:
                log("queued %d relevant update(s)" % n)
            safe_write_state(state)
            # Anti hot-loop: a healthy long poll blocks ~POLL_TIMEOUT,
            # so an instant return means something odd upstream; keep
            # at least a second between cycles.
            elapsed = time.time() - cycle_start
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
        else:
            state["errors"] += 1
            safe_write_state(state)
            log("getUpdates failed: %s; backoff %ss" % (
                str(result.get("description", result))[:200], backoff))
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
    log("listener.stop present; exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
