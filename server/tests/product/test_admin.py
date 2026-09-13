from pathlib import Path
import os
import shutil
import subprocess

import pytest

from shuxueshuo_server.product.config import Settings, REPO
from shuxueshuo_server.product.errors import Conflict, ProductError


def test_settings_reinstall_keeps_passwords_and_instance(tmp_path):
    root = tmp_path / 'data with spaces'
    first = Settings.load('local', root, 'test', 55432, initialize=True)
    original = {p.name: p.read_bytes() for p in (root / 'config').iterdir()}
    second = Settings.load('local', root, 'test', initialize=True)
    assert first.credentials == second.credentials
    assert second.port == 55432
    assert original == {p.name: p.read_bytes() for p in (root / 'config').iterdir()}
    with pytest.raises(Conflict): Settings.load('local', root, 'different', initialize=True)
    with pytest.raises(Conflict): Settings.load('local', root, 'test', 55433, initialize=True)
    with pytest.raises(ProductError): Settings.load('local', root / 'work/nested', 'test', initialize=True)


def test_status_does_not_initialize_config(tmp_path):
    root = tmp_path / 'not-installed'
    with pytest.raises(ProductError): Settings.load('local', root, 'test')
    assert not root.exists()


def test_release_packaged_manage_dispatches_without_repository(tmp_path):
    # Validate the offline package's relative layout without invoking Docker.
    package = tmp_path / 'release' / 'scripts'
    shutil.copytree(REPO / 'deploy/product', package)
    result = subprocess.run([str(package / 'manage.sh'), '--mode', 'server', '--data-dir', str(tmp_path / 'absent'), 'status'],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert '实例尚未安装' in result.stderr
    assert not (tmp_path / 'absent').exists()


def test_script_syntax():
    scripts = sorted((REPO / 'deploy/product').rglob('*.sh'))
    for script in scripts:
        subprocess.run(['bash', '-n', str(script)], check=True, capture_output=True)


def release_repository(tmp_path):
    repo = tmp_path / 'source tree'
    shutil.copytree(REPO / 'deploy/product', repo / 'deploy/product')
    (repo / 'server').mkdir()
    (repo / 'server/content.txt').write_text('committed source')
    (repo / '.gitignore').write_text('server/ignored.txt\n')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture']):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    return repo


@pytest.mark.parametrize('dirty', ['tracked', 'untracked', 'staged'])
def test_release_rejects_dirty_tree_before_docker(tmp_path, dirty):
    repo = release_repository(tmp_path)
    target = repo / ('untracked.txt' if dirty == 'untracked' else 'server/content.txt')
    target.write_text('uncommitted')
    if dirty == 'staged':
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    output = tmp_path / 'release'
    result = subprocess.run([str(repo / 'deploy/product/build-release.sh'), '--release', 'test-v1',
                             '--platform', 'linux/arm64', '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 2 and '干净工作树' in result.stderr
    assert not output.exists()


def test_release_uses_committed_archive_not_live_or_ignored_files(tmp_path):
    repo = release_repository(tmp_path)
    revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    readme = (repo / 'deploy/product/README.md').read_bytes()
    (repo / 'server/ignored.txt').write_text('must not enter image')
    binary = tmp_path / 'bin'
    binary.mkdir()
    # Fake the image transport only. Real git archive, tar, release packaging and checksums run.
    docker = binary / 'docker'
    docker.write_text('''#!/usr/bin/env python3
import os,sys,io,json,tarfile
from pathlib import Path
a=sys.argv[1:]
if a[:2]==['buildx','build']:
    context=Path(a[-1])
    assert (context/'server/content.txt').read_text()=='committed source'
    assert not (context/'server/ignored.txt').exists()
    (Path(os.environ['TEST_SOURCE_REPO'])/'deploy/product/README.md').write_text('changed during build')
elif a[:2]==['image','inspect']:
    print('sha256:'+'a'*64)
elif a[0]=='save':
    # Packaging reads content IDs from Docker's archive manifest, not inspect.
    tags=a[a.index('-o')+2:]
    manifest=[{'Config': str(i)*64+'.json', 'RepoTags': [tag], 'Layers': []}
              for i,tag in enumerate(tags,1)]
    content=json.dumps(manifest).encode()
    with tarfile.open(a[a.index('-o')+1], 'w') as archive:
        info=tarfile.TarInfo('manifest.json'); info.size=len(content)
        archive.addfile(info,io.BytesIO(content))
''')
    docker.chmod(0o755)
    output = tmp_path / 'release'
    subprocess.run([str(repo / 'deploy/product/build-release.sh'), '--release', 'test-v1',
                    '--platform', 'linux/arm64', '--output', str(output)], check=True, capture_output=True,
                   env={**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH'], 'TEST_SOURCE_REPO': str(repo)})
    assert f'PRODUCT_SOURCE_REVISION={revision}\n' in (output / 'release.env').read_text()
    assert (output / 'scripts/README.md').read_bytes() == readme
