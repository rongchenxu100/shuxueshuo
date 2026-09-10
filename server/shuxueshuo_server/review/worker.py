"""Single local worker process; HTTP/SSE disconnects never cancel work."""
import argparse
import fcntl
import time
import os
import subprocess
import sys

from .store import ReviewStore


def execute(store, run_id, pipeline):
    try:
        pipeline(store, run_id)
        if store.get(run_id).get("target_dependencies"):
            from .rebuild import BuildGuard
            BuildGuard(store, run_id).check()
        store.finish(run_id)
    except Exception as exc:
        store.finish(run_id, error=f"{type(exc).__name__}: {exc}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    store = ReviewStore()
    if args.run_id:
        from .pipeline import generate
        execute(store, args.run_id, generate)
        return
    with (store.root / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Review worker 已在运行；仅允许一个 worker") from None
        store.interrupt_unfinished()
        while True:
            run_id = store.claim()
            if run_id:
                # A fresh interpreter loads current code for every queued run.
                result = subprocess.run([sys.executable, "-m", "shuxueshuo_server.review.worker", "--run-id", run_id],
                    env={**os.environ, "REVIEW_DATA_DIR": str(store.root)})
                if store.get(run_id)["status"] == "running":
                    store.finish(run_id, error=f"worker 子进程退出 {result.returncode}，执行未完成")
            if args.once:
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
