"""Archive a completed debug directory without machine-local paths/timestamps."""
import argparse
import gzip
import io
from pathlib import Path
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
with args.output.open('wb') as target, gzip.GzipFile(fileobj=target, mode='wb', mtime=0, filename='') as zipped, tarfile.open(fileobj=zipped, mode='w|') as archive:
    # Store hard-linked latest aliases once as tar links to their content versions.
    seen = {}
    for path in sorted(args.directory.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(args.directory).as_posix()
        stat = path.stat()
        identity = (stat.st_dev, stat.st_ino)
        info = tarfile.TarInfo(name)
        info.mode = 0o644
        if identity in seen:
            info.type = tarfile.LNKTYPE
            info.linkname = seen[identity]
            archive.addfile(info)
        else:
            data = path.read_bytes()
            assert b'/Users/' not in data, f'local path in {name}'
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
            seen[identity] = name
