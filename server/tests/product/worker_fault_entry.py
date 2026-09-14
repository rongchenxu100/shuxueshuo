"""Test-only process boundary: real Celery/supervisor, sleeping child, no model access."""
import os
import subprocess
import sys
from pathlib import Path

from shuxueshuo_server.product.runtime_config import load_runtime
from shuxueshuo_server.product.transport import celery_app

runtime = load_runtime()
client = celery_app(runtime, sys.argv[1])
original = subprocess.Popen
marker = Path(sys.argv[2])
def launch(command, **kwargs):
    if 'shuxueshuo_server.product.runner' in command:
        command = [sys.executable, '-c', 'import time; time.sleep(120)']
        process = original(command, **kwargs)
        marker.write_text(str(process.pid))
        return process
    return original(command, **kwargs)
subprocess.Popen = launch
client.worker_main(['worker', '--pool=threads', '--concurrency=1', '--loglevel=WARNING', '--without-gossip', '--without-mingle', '-n', 'fault@%h'])
