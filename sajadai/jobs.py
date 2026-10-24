"""The sync queue: the scheduler and the «تازه‌سازی» button put jobs here instead of running them on the spot,
and two workers run them in order. A job already waiting isn't queued twice; a manual run jumps ahead of
the scheduled ones. Each provider retries on its own (pipeline.run_provider); a whole sync that failed is
tried again later with exponential backoff (2, 8, 32 minutes)."""
import heapq, itertools, threading, time

_q = []                 # (not_before, priority, seq, user_id, job, attempt)
_waiting = set()        # (user_id, job) queued or running
_cv = threading.Condition()
_seq = itertools.count()
_started = False
stats = {"done": 0, "failed": 0, "retried": 0, "running": []}
BACKOFF = (120, 480, 1920)


def enqueue(user_id, job="refresh", manual=False, delay=0, attempt=0):
    key = (user_id, job)
    with _cv:
        if key in _waiting:
            return False
        _waiting.add(key)
        heapq.heappush(_q, (time.time() + delay, 0 if manual else 1, next(_seq), user_id, job, attempt, manual))
        _cv.notify()
    return True


def pending():
    with _cv:
        return [{"user": u, "job": j, "in": max(0, round(nb - time.time())), "attempt": a} for nb, _, _, u, j, a, _ in sorted(_q)]


def _run(user_id, job, manual):
    from . import pipeline
    if job == "refresh":
        return pipeline.refresh(user_id, force=manual)
    if job == "repocheck":
        pipeline.repo_check(user_id)
        return True
    raise ValueError(job)


def _worker():
    while True:
        with _cv:
            while not _q or _q[0][0] > time.time():
                _cv.wait(timeout=max(1.0, (_q[0][0] - time.time()) if _q else 30))
            nb, pr, seq, user_id, job, attempt, manual = heapq.heappop(_q)
            stats["running"].append((user_id, job))
        ok = False
        try:
            ok = bool(_run(user_id, job, manual))
        except Exception as e:  # noqa: BLE001 — a job's error is the job's, the worker keeps going
            print(f"job {job} for {user_id}: {e}", flush=True)
        with _cv:
            stats["running"].remove((user_id, job))
            _waiting.discard((user_id, job))
            if ok:
                stats["done"] += 1
            elif attempt < len(BACKOFF):
                stats["retried"] += 1
            else:
                stats["failed"] += 1
        if not ok and attempt < len(BACKOFF) and job == "refresh":
            enqueue(user_id, job, delay=BACKOFF[attempt], attempt=attempt + 1)


def start(workers=2):
    global _started
    if _started:
        return
    _started = True
    for i in range(workers):
        threading.Thread(target=_worker, daemon=True, name=f"sync-{i}").start()
