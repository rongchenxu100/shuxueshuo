"""Instance-owned configuration. No module-level environment or filesystem writes."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import secrets
import shutil
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy import URL

from .errors import Conflict, ProductError

REPO = Path(__file__).resolve().parents[3]


def default_root(mode):
    if mode == 'server':
        return Path('/srv/shuxueshuo')
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/shuxueshuo/local'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'shuxueshuo/local'


def write_private(path, values):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = ''.join(f"{k}='{str(v).replace(chr(39), chr(92)+chr(39))}'\n" for k, v in values.items())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass
class Settings:
    mode: str
    root: Path
    instance: str
    port: int
    pg_bin: Path
    credentials: dict

    @property
    def artifact_root(self):
        return self.root / 'artifacts'

    @property
    def pgdata(self):
        return self.root / 'postgres'

    def url(self, role='app', *, database='product'):
        container = os.environ.get('PRODUCT_IN_CONTAINER') == '1'
        return URL.create('postgresql+psycopg', username='product_' + role,
            password=self.credentials[role], host='postgres' if container else '127.0.0.1',
            port=5432 if container else self.port, database=database).render_as_string(hide_password=False)

    @classmethod
    def load(cls, mode, data_dir=None, instance=None, port=None, *, initialize=False, pg_bin=None):
        root = Path(data_dir or os.environ.get('PRODUCT_DATA_DIR') or default_root(mode)).expanduser().absolute()
        # Resolve configured root once; storage itself rejects subsequent symlink traversal.
        root = root.resolve()
        if root == REPO or REPO in root.parents or root == Path('/'):
            raise ProductError('config.data_root_must_be_outside_repository')
        if any((parent / 'config/local.env').exists() or (parent / 'config/compose.env').exists() for parent in root.parents):
            raise ProductError('config.nested_instance_root')
        instance = instance or mode
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', instance):
            raise ProductError('config.instance')
        config_file = root / 'config' / ('local.env' if mode == 'local' else 'compose.env')
        if initialize:
            for d in ('config', 'artifacts', 'work', 'backups', 'logs', 'locks'):
                (root / d).mkdir(mode=0o700, parents=True, exist_ok=True)
        values = dict(dotenv_values(config_file)) if config_file.exists() else {}
        if values and (values['PRODUCT_INSTANCE'] != instance or (not os.environ.get('PRODUCT_IN_CONTAINER') and values['PRODUCT_DATA_DIR'] != str(root))):
            raise Conflict('config.instance_directory_mismatch')
        port = port or int(values.get('PRODUCT_DB_PORT', 5432))
        if not 1024 <= port <= 65535 or (values and port != int(values['PRODUCT_DB_PORT'])):
            raise Conflict('config.port_mismatch')
        binary = pg_bin or os.environ.get('PRODUCT_PG_BIN_DIR') or values.get('PRODUCT_PG_BIN_DIR')
        if binary is None and mode == 'local':
            candidates = [Path('/opt/homebrew/opt/postgresql@17/bin'), Path('/usr/local/opt/postgresql@17/bin')]
            binary = next((str(p) for p in candidates if (p / 'pg_ctl').exists()), None)
            if binary is None and shutil.which('pg_ctl'):
                binary = str(Path(shutil.which('pg_ctl')).parent)
        binary = Path(binary or '/usr/bin')
        if not values:
            if not initialize:
                raise ProductError('config.not_installed')
            write_private(config_file, dict(PRODUCT_INSTANCE=instance, PRODUCT_DATA_DIR=os.environ.get('PRODUCT_HOST_DATA_DIR', str(root)), PRODUCT_DB_PORT=port, PRODUCT_PG_BIN_DIR=binary))
        credentials = {}
        for role in ('app', 'migration', 'bootstrap'):
            path = root / 'config' / (role + '.env')
            if not path.exists():
                if not initialize:
                    raise ProductError('config.credentials_missing')
                write_private(path, {f'PRODUCT_{role.upper()}_PASSWORD': secrets.token_urlsafe(32)})
            if path.stat().st_mode & 0o077:
                raise ProductError('config.credentials_permissions')
            credentials[role] = dotenv_values(path)[f'PRODUCT_{role.upper()}_PASSWORD']
        return cls(mode, root, instance, port, binary, credentials)

    def check_native(self):
        for tool in ('postgres', 'initdb', 'pg_ctl', 'pg_dump', 'pg_restore', 'psql'):
            result = subprocess.run([str(self.pg_bin / tool), '--version'], capture_output=True, text=True, check=True)
            if not re.search(r'\b17\.', result.stdout):
                raise ProductError('postgres.major_version_mismatch')
