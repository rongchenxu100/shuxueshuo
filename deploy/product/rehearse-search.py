"""Repackage cached dependencies and rehearse student search on an isolated Docker network."""

import argparse
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run(*command, capture=False, env=None):
    result = subprocess.run(command, check=True, text=True, capture_output=capture, env=env)
    return result.stdout.strip() if capture else None


def private_file(path, content):
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def image_info(image):
    details = json.loads(run('docker', 'image', 'inspect', image, capture=True))[0]
    if details.get('Os') and details.get('Architecture'):
        return details
    for platform in ('linux/amd64', 'linux/arm64'):
        try:
            details = json.loads(run('docker', 'image', 'inspect', '--platform', platform, image, capture=True))[0]
        except subprocess.CalledProcessError:
            continue
        if details.get('Os') and details.get('Architecture'):
            return details
    raise RuntimeError(f'No runnable locally cached platform for {image}')


def offline_recipe(kind, base):
    original = (REPO / f'deploy/product/Dockerfile.{kind}').read_text()
    tail = original[original.index('COPY server /app/server'):]
    return (
        f'FROM {base}\n'
        'COPY deploy/product/requirements.lock /tmp/rehearsal-requirements.lock\n'
        'RUN cmp /tmp/requirements.lock /tmp/rehearsal-requirements.lock\n'
        'RUN rm -rf /app/server /app/tools /app/internal /app/site\n' + tail
    )


def prepare_fixtures(output):
    fixtures = output / 'fixtures'
    fixtures.mkdir()
    source = REPO / 'server/tests/solver/fixtures'
    shutil.copytree(source / 'graph-guided-stage-two/recorded/q01-20261018-02', fixtures / 'recording')
    shutil.copyfile(source / 'graph-guided-stage-one/quadratic-always/q01/notation.gold.json', fixtures / 'candidate.json')
    shutil.copyfile(REPO / 'server/tests/search/server_rehearsal.py', fixtures / 'server_rehearsal.py')
    shutil.copyfile(REPO / 'deploy/ocr/sidecar_server.py', fixtures / 'sidecar_server.py')
    return fixtures


def read_environment(path):
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        name, value = line.split('=', 1)
        parsed = shlex.split(value)
        values[name] = parsed[0] if parsed else ''
    return values


def safe_source(image, output, identity):
    source = output / 'source'
    source.mkdir()
    container = identity + '-source'
    run('docker', 'create', '--pull=never', '--network=none', '--name', container, image)
    try:
        run('docker', 'cp', container + ':/app/server', str(source / 'server'))
    finally:
        subprocess.run(['docker', 'rm', '-f', container], check=False)
    forbidden = {'.env', '.git', '.venv', '.venv-ocr', 'tests'}
    if any((source / 'server' / name).exists() for name in forbidden):
        raise RuntimeError('Extracted runtime contains private or test files')
    sidecar = source / 'deploy/ocr'
    sidecar.mkdir(parents=True)
    for name in ('sidecar_server.py', 'preheat_models.py'):
        shutil.copyfile(REPO / 'deploy/ocr' / name, sidecar / name)
    return source


def compose_overlay(output, images, uid, identity):
    fixture_mount = f'{output / "fixtures"}:/rehearsal:ro'
    api_environment = {'SEARCH_OFFLINE_REHEARSAL': '1'}
    services = {name: {'pull_policy': 'never', 'platform': value['Os'] + '/' + value['Architecture']}
                for name, value in images.items() if name not in ('app', 'nginx')}
    services['admin']['environment'] = {'PRODUCT_MODE': 'server', 'PRODUCT_OCR_URL': 'http://ocr:8080'}
    for name in ('api', 'worker', 'publisher'):
        services[name] = {'pull_policy': 'never', 'platform': images['app']['Os'] + '/' + images['app']['Architecture']}
    services['api'].update({
        'environment': api_environment,
        'env_file': [str(output / 'api.env')],
        'volumes': [fixture_mount],
        'command': ['/opt/product/bin/python', '/rehearsal/server_rehearsal.py', 'api'],
        'networks': {'default': {'aliases': ['shuxueshuo.com', 'www.shuxueshuo.com']}},
    })
    services['ocr'].update({
        'environment': api_environment,
        'volumes': [fixture_mount],
        'command': ['python', '/rehearsal/server_rehearsal.py', 'ocr'],
    })
    services['nginx'] = {
        'image': images['nginx']['Id'], 'pull_policy': 'never',
        'platform': images['nginx']['Os'] + '/' + images['nginx']['Architecture'],
        'network_mode': 'service:api', 'depends_on': {'api': {'condition': 'service_healthy'}},
        'volumes': [f'{output / "shuxueshuo.conf"}:/etc/nginx/conf.d/default.conf:ro',
                    f'{output / "cert"}:/home/ronghao/cert/shuxueshuo:ro',
                    f'{REPO / "site"}:/home/ronghao/code/shuxueshuo/site:ro'],
        'healthcheck': {'test': ['CMD', 'nginx', '-t'], 'interval': '2s', 'timeout': '3s', 'retries': 30},
    }
    services['fixture'] = {
        'image': '${PRODUCT_APP_IMAGE}', 'pull_policy': 'never', 'profiles': ['fixture'],
        'platform': images['app']['Os'] + '/' + images['app']['Architecture'], 'user': uid,
        'environment': {'PRODUCT_IN_CONTAINER': '1', 'PRODUCT_MODE': 'server',
                        'PRODUCT_INSTANCE': 'search-rehearsal', 'PRODUCT_DATA_DIR': '/var/lib/shuxueshuo'},
        'env_file': [str(output / 'api.env')], 'working_dir': '/app/server',
        'entrypoint': ['/opt/product/bin/python', '/rehearsal/server_rehearsal.py'],
        'volumes': [f'{output / "data"}:/var/lib/shuxueshuo', fixture_mount],
    }
    lines = ['services:']
    for name, configuration in services.items():
        lines.append(f'  {name}:')
        if name in ('postgres', 'rabbitmq', 'api'):
            lines.append('    ports: !reset []')
        lines.extend(f'    {key}: {json.dumps(value)}' for key, value in configuration.items())
    lines.extend(['networks:', '  default:', '    internal: true'])
    lines.extend(['volumes:', '  postgres_data:', f'    name: {json.dumps(identity + "_postgres_data")}',
                  '  rabbitmq_data:', f'    name: {json.dumps(identity + "_rabbitmq_data")}'])
    return '\n'.join(lines) + '\n'


def redact_configuration(value):
    if isinstance(value, dict):
        return {key: '[redacted]' if any(word in key.upper() for word in ('PASSWORD', 'SECRET', 'COOKIE', 'ACCESS_KEY'))
                else redact_configuration(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_configuration(item) for item in value]
    return value


def fixture_summary(data):
    state = json.loads((data / 'work/rehearsal-state.json').read_text())
    return {name: state[name] for name in ('limits', 'usage', 'fixture_seeded_tickets')}


def validate_database(evidence, source):
    revision = run(sys.executable, str(REPO / 'deploy/product/alembic-head.py'),
                   str(source / 'server/alembic/versions'), capture=True)
    if evidence != {'revision': revision, 'product_jobs': 0, 'product_builds': 0}:
        raise RuntimeError('Unexpected migration revision or product work during offline rehearsal')


def validate_configuration(configuration, output):
    services = configuration['services']
    for name, service in services.items():
        if service.get('ports'):
            raise RuntimeError(f'Rehearsal must not publish host ports: {name}')
    if set(configuration['networks']) != {'default'} or not configuration['networks']['default'].get('internal'):
        raise RuntimeError('Rehearsal network must be internal')
    for name in ('api', 'worker', 'publisher'):
        service = services[name]
        if set(service['depends_on']) != {'postgres', 'rabbitmq', 'ocr'}:
            raise RuntimeError(f'Production dependencies changed: {name}')
        mount = next(item for item in service['volumes'] if item['target'] == '/app/server/.env')
        if Path(mount['source']) != output / 'source/server/.env' or not mount.get('read_only'):
            raise RuntimeError(f'Unsafe application environment mount: {name}')
    admin = services['admin']
    if not admin.get('read_only') or '/tmp' not in admin.get('tmpfs', []) or not admin.get('security_opt'):
        raise RuntimeError('Production admin hardening must remain enabled')
    if services['api']['stop_grace_period'] not in ('10m0s', '10m', '600s'):
        raise RuntimeError('Production API drain grace period changed')
    ocr_source = next(item for item in services['ocr']['volumes'] if item['target'] == '/opt/shuxueshuo')
    if Path(ocr_source['source']) != output / 'source' or not ocr_source.get('read_only'):
        raise RuntimeError('OCR must mount only the safe source copy')
    for name in ('admin', 'api', 'worker', 'publisher', 'ocr'):
        mount = next(item for item in services[name]['volumes'] if item['target'] == '/var/lib/shuxueshuo')
        if Path(mount['source']) != output / 'data':
            raise RuntimeError(f'Unexpected persistent data root: {name}')


def wait_container(name, command, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        checked = subprocess.run(['docker', 'exec', name, *command], capture_output=True, check=False)
        if checked.returncode == 0:
            return
        state = run('docker', 'inspect', '--format', '{{.State.Running}}', name, capture=True)
        if state != 'true':
            raise RuntimeError(f'{name} exited before becoming ready')
        time.sleep(1)
    raise TimeoutError(f'{name} did not become ready')


def rehearse(args, output):
    identity = 'search-rehearsal-' + secrets.token_hex(5)
    images = {key: image_info(getattr(args, key)) for key in ('app', 'admin', 'postgres', 'nginx', 'rabbitmq', 'ocr')}
    report = {
        'kind': 'offline-search-compose-rehearsal/v2',
        'source_revision': run('git', '-C', str(REPO), 'rev-parse', 'HEAD', capture=True),
        'working_tree': run('git', '-C', str(REPO), 'status', '--short', capture=True),
        'bases': {key: {'id': value['Id'], 'platform': value['Os'] + '/' + value['Architecture']}
                  for key, value in images.items()},
        'paid_calls': 0,
        'real_sms_calls': 0,
        'production_deployment': False,
        'passed': False,
        'limitations': ['Cached dependency layers, not a fresh dependency installation.',
                        'Synthetic public review, recorded stage two, fixture SMS and OCR inference.',
                        'Real OCR image dependencies; no Paddle model warmup, accuracy or performance claim.',
                        'Fixture API entrypoint replaces Uvicorn startup only to install offline adapters.',
                        ('Nginx shares the API network namespace instead of running on the host; '
                         'fixture Uvicorn trusts its loopback proxy instead of the host bridge.'),
                        'Production worker and publisher start but receive no product builds.',
                        'This is not an archived release bundle or a target-server capacity test.'],
    }
    tags = {kind: 'docker.io/library/' + identity + '-' + kind for kind in ('app', 'admin')}
    for kind, tag in tags.items():
        recipe = output / f'{kind}.Dockerfile'
        recipe.write_text(offline_recipe(kind, getattr(args, kind)))
        shutil.copyfile(REPO / f'deploy/product/Dockerfile.{kind}.dockerignore', Path(str(recipe) + '.dockerignore'))
        run('docker', 'build', '--pull=false', '--network=none', '--platform', report['bases'][kind]['platform'],
            '-f', str(recipe), '-t', tag, str(REPO))
        report[kind + '_image'] = image_info(tag)['Id']
        run('docker', 'run', '--rm', '--pull=never', '--network=none',
            '--entrypoint', '/opt/product/bin/python', tag, '-c',
            'from pathlib import Path; root=Path("/app/server"); '
            'assert not any((root/name).exists() for name in (".env", ".venv", ".venv-ocr", "tests"))')
    data = output / 'data'
    data.mkdir(mode=0o700)
    prepare_fixtures(output)
    source = safe_source(tags['app'], output, identity)
    (output / 'home/.paddlex').mkdir(parents=True)
    uid = f'{os.getuid()}:{os.getgid()}'
    common = ['--pull=never', '--user', uid, '-e', 'PRODUCT_IN_CONTAINER=1', '-e', 'PRODUCT_MODE=server',
              '-e', 'PRODUCT_INSTANCE=search-rehearsal', '-e', 'PRODUCT_DATA_DIR=/var/lib/shuxueshuo',
              '-v', f'{data}:/var/lib/shuxueshuo']
    admin = ['docker', 'run', '--rm', '--network=none', '--read-only', '--tmpfs', '/tmp',
             '--security-opt', 'no-new-privileges:true', *common, tags['admin'], '--mode', 'server',
             '--instance', 'search-rehearsal', '--data-dir', '/var/lib/shuxueshuo']
    run(*admin, 'configure')
    bootstrap = read_environment(data / 'config/bootstrap.env')['PRODUCT_BOOTSTRAP_PASSWORD']
    private_file(output / 'api.env', '\n'.join([
        'PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED=1', 'PRODUCT_OCR_URL=http://ocr:8080',
        'AUTH_ENVIRONMENT=production', 'AUTH_ORIGIN=https://shuxueshuo.com', 'AUTH_COOKIE_SECURE=1',
        'AUTH_SMS_MODE=aliyun_sms', 'AUTH_SECRET=' + secrets.token_urlsafe(48),
        'ALIYUN_SMS_ACCESS_KEY_ID=offline-fixture', 'ALIYUN_SMS_ACCESS_KEY_SECRET=offline-fixture',
        'ALIYUN_SMS_SIGN_NAME=offline-fixture', 'ALIYUN_SMS_TEMPLATE_CODE=offline-fixture',
        'RUN_LLM_INTEGRATION=1', 'REVIEW_BACKEND=product',
        'SEARCH_OFFLINE_REHEARSAL=1',
    ]) + '\n')
    private_file(source / 'server/.env', (output / 'api.env').read_text())
    certificate = output / 'cert'
    certificate.mkdir()
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=shuxueshuo.com', '-keyout', str(certificate / 'shuxueshuo.com.key'),
        '-out', str(certificate / 'shuxueshuo.com.pem'))
    (certificate / 'shuxueshuo.com.key').chmod(0o600)
    proxy = output / 'shuxueshuo.conf'
    proxy.write_bytes((REPO / 'deploy/nginx/shuxueshuo.conf').read_bytes())
    report['nginx_config_sha256'] = hashlib.sha256(proxy.read_bytes()).hexdigest()
    overlay = output / 'compose.rehearsal.yml'
    overlay.write_text(compose_overlay(output, images, uid, identity))
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PRODUCT_', 'COMPOSE_', 'SEARCH_'))}
    environment.update({
        'PRODUCT_INSTANCE': 'search-rehearsal', 'PRODUCT_DATA_DIR': str(data),
        'PRODUCT_POSTGRES_IMAGE': images['postgres']['Id'], 'PRODUCT_ADMIN_IMAGE': tags['admin'],
        'PRODUCT_APP_IMAGE': tags['app'], 'PRODUCT_OCR_IMAGE': images['ocr']['Id'],
        'PRODUCT_RABBITMQ_IMAGE': images['rabbitmq']['Id'], 'PRODUCT_BOOTSTRAP_PASSWORD': bootstrap,
        'PRODUCT_RELEASE_ID': identity, 'PRODUCT_UID': str(os.getuid()), 'PRODUCT_GID': str(os.getgid()),
        'PRODUCT_REPO_HOST': str(source), 'PRODUCT_HOST_HOME': str(output / 'home'),
        'PRODUCT_BROKER_USER': 'pending', 'PRODUCT_BROKER_PASSWORD': 'pending',
        'PRODUCT_BROKER_VHOST': 'pending', 'PRODUCT_BROKER_COOKIE': 'pending',
    })
    originals = [REPO / 'deploy/product' / name for name in ('compose.yml', 'compose.server.yml', 'compose.app.yml')]
    compose = ['docker', 'compose', '--project-name', identity]
    for path in [*originals, overlay]:
        compose.extend(['-f', str(path)])
    report['compose_sources_sha256'] = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in originals}
    report['compose_overlay_sha256'] = hashlib.sha256(overlay.read_bytes()).hexdigest()
    report['project'] = identity

    def composed(*arguments, capture=False):
        return run(*compose, *arguments, env=environment, capture=capture)

    def administer(operation):
        return composed('run', '--rm', '--no-deps', 'admin', '--mode', 'server',
                        '--instance', 'search-rehearsal', '--data-dir', '/var/lib/shuxueshuo', operation, capture=True)

    containers = {}
    try:
        configuration = json.loads(composed('--profile', 'admin', '--profile', 'fixture', 'config', '--format', 'json', capture=True))
        validate_configuration(configuration, output)
        composed('up', '-d', '--wait', '--wait-timeout', '120', 'postgres')
        report['installation'] = json.loads(administer('install'))
        report['runtime_installation'] = json.loads(administer('services-install'))
        runtime_values = read_environment(data / 'config/runtime.env')
        environment.update({'PRODUCT_' + key: value for key, value in runtime_values.items()
                            if key in ('BROKER_USER', 'BROKER_PASSWORD', 'BROKER_VHOST', 'BROKER_COOKIE')})
        configuration = json.loads(composed('--profile', 'admin', '--profile', 'fixture', 'config', '--format', 'json', capture=True))
        validate_configuration(configuration, output)
        (output / 'compose.resolved.redacted.json').write_text(
            json.dumps(redact_configuration(configuration), ensure_ascii=False, indent=2) + '\n')
        composed('up', '-d', '--wait', '--wait-timeout', '240', 'rabbitmq', 'ocr', 'api', 'worker', 'publisher', 'nginx')
        for name in ('postgres', 'rabbitmq', 'ocr', 'api', 'worker', 'publisher', 'nginx'):
            containers[name] = composed('ps', '-q', name, capture=True)
            if not containers[name] or '\n' in containers[name]:
                raise RuntimeError(f'Expected exactly one {name} container')
        report['doctor'] = json.loads(administer('services-doctor'))
        composed('run', '--rm', '--no-deps', 'fixture', 'exercise')
        composed('restart', '--timeout', '600', 'api')
        wait_container(containers['api'], ['/opt/product/bin/python', '-c',
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"])
        composed('restart', 'nginx')
        wait_container(containers['nginx'], ['nginx', '-t'])
        composed('run', '--rm', '--no-deps', 'fixture', 'recovery')
        composed('run', '--rm', '--no-deps', '--entrypoint', '/opt/product/bin/python', 'fixture',
                 '-m', 'shuxueshuo_server.search.maintenance', '--mode', 'server', '--instance', 'search-rehearsal', 'cleanup')
        report['checks'] = json.loads((data / 'work/rehearsal-report.json').read_text())
        report['admission'] = fixture_summary(data)
        report['containers'] = {}
        for name, container in containers.items():
            details = json.loads(run('docker', 'inspect', container, capture=True))[0]
            if details['HostConfig'].get('PortBindings'):
                raise RuntimeError(f'Unexpected published ports: {name}')
            if not details['State']['Running']:
                raise RuntimeError(f'Service exited during rehearsal: {name}')
            if details['State'].get('OOMKilled'):
                raise RuntimeError(f'Service OOM during rehearsal: {name}')
            report['containers'][name] = {
                'image': details['Image'], 'command': details['Config']['Cmd'],
                'user': details['Config']['User'], 'state': details['State']['Status'],
                'health': details['State'].get('Health', {}).get('Status'),
                'oom_killed': details['State']['OOMKilled'],
                'processes': run('docker', 'top', container, '-eo', 'pid,ppid,args', capture=True),
            }
        for name in ('api', 'ocr'):
            interpreter = '/opt/product/bin/python' if name == 'api' else 'python'
            output_json = run('docker', 'exec', containers[name], interpreter, '-c',
                'import json,os,pathlib; matches=[]; '
                '[(matches.append(path.name)) for path in pathlib.Path("/proc").iterdir() '
                'if path.name.isdecimal() and int(path.name)!=os.getpid() '
                'and path.joinpath("cmdline").exists() '
                'and b"/rehearsal/server_rehearsal.py\\x00' + name + '\\x00" in path.joinpath("cmdline").read_bytes()]; '
                'assert len(matches)==1,matches; print(json.dumps(matches))', capture=True)
            report['containers'][name]['service_processes'] = json.loads(output_json)
        for name in ('worker', 'publisher'):
            heartbeat = json.loads((data / 'locks' / (name + '-heartbeat.json')).read_text())
            if not 0 <= time.time() - heartbeat['at'] < 30:
                raise RuntimeError(f'Stale {name} heartbeat')
            report['containers'][name]['heartbeat'] = heartbeat
        evidence = composed('run', '--rm', '--no-deps', '--entrypoint', '/opt/product/bin/python', 'fixture', '-c',
            'import json; from sqlalchemy import text; '
            'from shuxueshuo_server.product.config import Settings; from shuxueshuo_server.product.db import engine; '
            'database=engine(Settings.load("server",instance="search-rehearsal").url("migration")); '
            'connection=database.connect(); '
            'evidence={"revision":connection.scalar(text("SELECT version_num FROM alembic_version")), '
            '"product_jobs":connection.scalar(text("SELECT count(*) FROM jobs")), '
            '"product_builds":connection.scalar(text("SELECT count(*) FROM builds"))}; '
            'connection.close(); database.dispose(); print(json.dumps(evidence))', capture=True)
        report['database'] = json.loads(evidence)
        validate_database(report['database'], source)
        report['passed'] = True
    finally:
        failed = sys.exc_info()[0] is not None
        log = subprocess.run([*compose, 'logs', '--no-color'], env=environment, text=True, capture_output=True, check=False)
        private_file(output / 'services.log', log.stdout + log.stderr)
        cleanup = subprocess.run([*compose, '--profile', 'fixture', 'down', '--volumes', '--remove-orphans', '--timeout', '600'],
                                 env=environment, text=True, capture_output=True, check=False)
        private_file(output / 'cleanup.log', cleanup.stdout + cleanup.stderr)
        report['cleanup_ok'] = cleanup.returncode == 0
        report['passed'] = report['passed'] and report['cleanup_ok']
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        if cleanup.returncode and not failed:
            raise RuntimeError(f'Compose cleanup failed; inspect {output / "cleanup.log"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, help='Existing local app image with the current requirements.lock')
    parser.add_argument('--admin', required=True, help='Existing local admin image with the current requirements.lock')
    parser.add_argument('--postgres', required=True, help='Existing local PostgreSQL 17 image')
    parser.add_argument('--nginx', required=True, help='Existing local Nginx image')
    parser.add_argument('--rabbitmq', required=True, help='Existing local RabbitMQ image')
    parser.add_argument('--ocr', required=True, help='Existing local production OCR image; inference remains fixture-only')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix='search-image-rehearsal-'))
    if output.resolve().is_relative_to(REPO):
        raise ValueError('Rehearsal data and fixture credentials must be outside the repository')
    if args.output:
        output.mkdir(mode=0o700)
    print(f'Offline rehearsal output: {output}', flush=True)
    try:
        rehearse(args, output)
    except BaseException as exc:
        report_path = output / 'report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else {
            'kind': 'offline-search-compose-rehearsal/v2', 'cleanup_ok': None,
        }
        report.update(passed=False, failure_type=type(exc).__name__)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
