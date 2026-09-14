"""Immutable local storage with descriptor-relative, no-follow traversal."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import stat
from typing import BinaryIO, Protocol
from uuid import uuid4

from .errors import Conflict, IntegrityFailure, ProductError


@dataclass(frozen=True)
class ObjectStat:
    size_bytes: int


@dataclass(frozen=True)
class StoredObject:
    storage_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    availability: str


class ArtifactStorage(Protocol):
    def put_immutable(self, key: str, stream: BinaryIO, expected_sha256: str | None = None) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def stat(self, key: str) -> ObjectStat: ...
    def verify(self, key: str, sha256: str, size: int) -> VerificationResult: ...


def parts(key):
    if not isinstance(key, str) or not key or key.startswith('/') or '\\' in key or '\x00' in key:
        raise ProductError('storage.invalid_key')
    result = key.split('/')
    if any(p in ('', '.', '..') or any(ord(c) < 32 for c in p) for p in result):
        raise ProductError('storage.invalid_key')
    if result[0] == '.tmp':
        raise ProductError('storage.reserved_key')
    return result


class LocalArtifactStorage:
    def __init__(self, root):
        self.root = Path(root).absolute()

    @contextmanager
    def _directory(self, relative=(), create=False):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags)
        try:
            for name in (*self.root.parts[1:], *relative):
                if name in ('.', '..'):
                    raise ProductError('storage.invalid_root')
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(name, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            yield fd
        finally:
            os.close(fd)

    def open(self, key):
        names = parts(key)
        with self._directory(names[:-1]) as fd:
            file_fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                os.close(file_fd)
                raise IntegrityFailure('storage.not_regular')
        return os.fdopen(file_fd, 'rb')

    def stat(self, key):
        with self.open(key) as stream:
            return ObjectStat(os.fstat(stream.fileno()).st_size)

    def verify(self, key, sha256, size):
        try:
            actual = self._hash(key)
        except FileNotFoundError:
            return VerificationResult(False, 'missing')
        except (OSError, IntegrityFailure):
            return VerificationResult(False, 'corrupt')
        ok = actual.sha256 == sha256 and actual.size_bytes == size
        return VerificationResult(ok, 'verified' if ok else 'corrupt')

    def _hash(self, key):
        h, size = sha256(), 0
        with self.open(key) as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
                size += len(chunk)
        return StoredObject(key, h.hexdigest(), size)

    def put_immutable(self, key, stream, expected_sha256=None):
        names = parts(key)
        with self._directory(('.tmp',), create=True) as tmp, self._directory(names[:-1], create=True) as dest:
            name = uuid4().hex
            file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=tmp)
            try:
                h, size = sha256(), 0
                with os.fdopen(file_fd, 'wb') as output:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                actual = StoredObject(key, h.hexdigest(), size)
                if expected_sha256 is not None and expected_sha256 != actual.sha256:
                    raise IntegrityFailure('storage.hash_mismatch')
                try:
                    os.link(name, names[-1], src_dir_fd=tmp, dst_dir_fd=dest, follow_symlinks=False)
                    os.fsync(dest)
                except FileExistsError:
                    if not self.verify(key, actual.sha256, size).ok:
                        raise Conflict('storage.key_conflict') from None
                return actual
            finally:
                os.unlink(name, dir_fd=tmp)
                os.fsync(tmp)

    def orphan_report(self, registered_keys):
        known = set(registered_keys)
        result = []
        if not self.root.exists():
            return result
        for directory, _, files in os.walk(self.root, followlinks=False):
            for filename in files:
                key = (Path(directory) / filename).relative_to(self.root).as_posix()
                if key not in known:
                    result.append(key)
        return sorted(result)
