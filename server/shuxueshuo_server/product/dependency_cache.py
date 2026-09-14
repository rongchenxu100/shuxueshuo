"""Process-local reuse of discovery for a server release, with change detection.

No snapshots are accepted from disk or another process. Each process discovers
its own release once; local development always uses fresh discovery. Database
lease/cancellation checks and the live OCR manifest remain outside this cache.
"""
from copy import deepcopy
from hashlib import sha256
import os
from threading import Lock

from shuxueshuo_server.review.dependencies import digest, inventory_paths, probe

from .config import REPO
from .errors import Conflict


class ReleaseDependencyCache:
    def __init__(self):
        self._lock = Lock()
        self._key = None
        self._snapshot = None

    def _key_for(self, root):
        files = []
        for path in inventory_paths(root):
            stat = path.stat()
            files.append((str(path.relative_to(root)), stat.st_dev, stat.st_ino,
                          stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        # Model configuration can be a live bind mount. Include content, not
        # just mtime, and environment used by dotenv interpolation/overrides.
        env_file = root / 'server/.env'
        config_hash = sha256(env_file.read_bytes()).hexdigest() if env_file.exists() else None
        return digest({'root': str(root.resolve()), 'files': files, 'config': config_hash,
                       'environment': dict(os.environ)})

    def get(self, root, discover):
        if (os.environ.get('PRODUCT_MODE') != 'server'
                or os.environ.get('PRODUCT_IN_CONTAINER') != '1'
                or not os.environ.get('PRODUCT_RELEASE_ID', '').strip()):
            return discover()
        # Single flight: concurrent API requests never duplicate expensive
        # discovery, and callers cannot mutate the shared snapshot.
        with self._lock:
            try:
                key = self._key_for(root)
                if key == self._key:
                    return deepcopy(self._snapshot)
                snapshot = discover()
                if self._key_for(root) != key:
                    raise Conflict('build.environment_changed')
            except Exception:
                self._key, self._snapshot = None, None
                raise
            self._key, self._snapshot = key, deepcopy(snapshot)
            return snapshot


_CACHE = ReleaseDependencyCache()


def release_dependencies():
    return _CACHE.get(REPO, probe)
