"""Local process liveness files contain no credentials or business payloads."""
import json
import os
import time


def pulse(runtime, name, version):
    path = runtime.settings.root / 'locks' / (name + '-heartbeat.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid': os.getpid(), 'version': version, 'at': time.time()}))
    temporary.chmod(0o600)
    temporary.replace(path)
