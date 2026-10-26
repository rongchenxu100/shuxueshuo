import copy
import importlib.util
import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SPECIFICATION = importlib.util.spec_from_file_location('container_rehearsal', REPO / 'deploy/product/rehearse-search.py')
rehearsal = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(rehearsal)


class OverlayLoader(yaml.SafeLoader):
    pass


OverlayLoader.add_constructor('!reset', lambda loader, node: loader.construct_sequence(node))


def images():
    return {name: {'Id': 'sha256:' + name, 'Os': 'linux', 'Architecture': 'amd64'}
            for name in ('app', 'admin', 'postgres', 'nginx', 'rabbitmq', 'ocr')}


def test_image_index_resolves_only_a_locally_inspectable_platform(monkeypatch):
    calls = []

    def inspect(*command, **_kwargs):
        calls.append(command)
        details = images()['rabbitmq'] if '--platform' in command else {'Id': 'index', 'Os': '', 'Architecture': ''}
        return json.dumps([details])

    monkeypatch.setattr(rehearsal, 'run', inspect)
    assert rehearsal.image_info('rabbitmq') == images()['rabbitmq']
    assert calls == [('docker', 'image', 'inspect', 'rabbitmq'),
                     ('docker', 'image', 'inspect', '--platform', 'linux/amd64', 'rabbitmq')]


def test_image_index_without_cached_layers_is_rejected_without_pulling(monkeypatch):
    calls = []

    def inspect(*command, **_kwargs):
        calls.append(command)
        if '--platform' in command and 'linux/amd64' in command:
            raise rehearsal.subprocess.CalledProcessError(1, command)
        return json.dumps([{'Id': 'index', 'Os': '', 'Architecture': ''}])

    monkeypatch.setattr(rehearsal, 'run', inspect)
    with pytest.raises(RuntimeError, match='No runnable locally cached platform'):
        rehearsal.image_info('rabbitmq')
    assert len(calls) == 3
    assert all(command[:3] == ('docker', 'image', 'inspect') for command in calls)


def resolved_configuration(output):
    services = {}
    for name in ('admin', 'api', 'worker', 'publisher', 'ocr'):
        services[name] = {'volumes': [{'source': str(output / 'data'), 'target': '/var/lib/shuxueshuo'}]}
    for name in ('api', 'worker', 'publisher'):
        services[name]['depends_on'] = {dependency: {'condition': 'service_healthy'}
                                        for dependency in ('postgres', 'rabbitmq', 'ocr')}
        services[name]['volumes'].append({'source': str(output / 'source/server/.env'),
                                         'target': '/app/server/.env', 'read_only': True})
    services['admin'].update(read_only=True, tmpfs=['/tmp'], security_opt=['no-new-privileges:true'])
    services['api']['stop_grace_period'] = '10m0s'
    services['ocr']['volumes'].append({'source': str(output / 'source'), 'target': '/opt/shuxueshuo', 'read_only': True})
    return {'services': services, 'networks': {'default': {'internal': True}}}


def test_overlay_retains_production_health_dependencies_and_runtime_hardening(tmp_path):
    overlay = yaml.load(rehearsal.compose_overlay(tmp_path, images(), '1000:1000', 'fixture-project'), Loader=OverlayLoader)
    services = overlay['services']
    for name in ('postgres', 'rabbitmq', 'api'):
        assert services[name]['ports'] == []
    for name in ('api', 'worker', 'publisher', 'ocr', 'admin'):
        assert 'depends_on' not in services[name]
        assert 'healthcheck' not in services[name]
        assert 'user' not in services[name]
        assert 'read_only' not in services[name]
        assert 'stop_grace_period' not in services[name]
    for name in ('worker', 'publisher', 'admin', 'postgres', 'rabbitmq'):
        assert 'command' not in services[name]
    assert services['ocr']['command'] == ['python', '/rehearsal/server_rehearsal.py', 'ocr']
    assert 'image' not in services['ocr']
    assert services['nginx']['network_mode'] == 'service:api'
    assert services['nginx']['image'] == 'sha256:nginx'
    assert overlay['networks'] == {'default': {'internal': True}}
    assert overlay['volumes']['postgres_data']['name'] == 'fixture-project_postgres_data'
    assert overlay['volumes']['rabbitmq_data']['name'] == 'fixture-project_rabbitmq_data'
    assert 'SEARCH_GENERATION_ACCOUNT_DAILY' not in json.dumps(overlay)
    assert 'SEARCH_RERUN_ACCOUNT_DAILY' not in json.dumps(overlay)


def test_overlay_allows_spaces_without_interpreting_paths_as_yaml(tmp_path):
    output = tmp_path / 'a directory: with spaces'
    overlay = yaml.load(rehearsal.compose_overlay(output, images(), '501:20', 'fixture-project'), Loader=OverlayLoader)
    assert overlay['services']['api']['env_file'] == [str(output / 'api.env')]
    assert overlay['services']['fixture']['volumes'][0] == f'{output / "data"}:/var/lib/shuxueshuo'


def test_fixture_summary_excludes_credentials_and_student_identifiers(tmp_path):
    (tmp_path / 'work').mkdir()
    public = {'limits': {'generation_account_daily': 10}, 'usage': {'generation': 100},
              'fixture_seeded_tickets': {'generation': 90}}
    (tmp_path / 'work/rehearsal-state.json').write_text(json.dumps({
        **public, 'cookies': {'session': 'secret'}, 'user_id': 'private-student', 'pending': 'private-submission',
    }))
    assert rehearsal.fixture_summary(tmp_path) == public


def test_database_evidence_follows_the_extracted_image_migration_head(tmp_path):
    migrations = tmp_path / 'server/alembic/versions'
    migrations.mkdir(parents=True)
    (migrations / 'first.py').write_text("revision = 'fixture-base'\ndown_revision = None\n")
    (migrations / 'next.py').write_text("revision = 'fixture-next'\ndown_revision = 'fixture-base'\n")
    evidence = {'revision': 'fixture-next', 'product_jobs': 0, 'product_builds': 0}
    rehearsal.validate_database(evidence, tmp_path)
    for changed in ({'revision': 'fixture-base'}, {'product_jobs': 1}, {'product_builds': 1}):
        with pytest.raises(RuntimeError, match='Unexpected migration revision or product work'):
            rehearsal.validate_database(evidence | changed, tmp_path)


def test_early_build_failure_writes_failed_report_without_command_credentials(tmp_path, monkeypatch):
    output = tmp_path / 'output'
    arguments = ['rehearse-search', '--output', str(output)]
    for name in images():
        arguments.extend(['--' + name, name])
    monkeypatch.setattr(rehearsal.sys, 'argv', arguments)

    def fail(*_args):
        raise RuntimeError('private command must not enter report')

    monkeypatch.setattr(rehearsal, 'rehearse', fail)
    with pytest.raises(RuntimeError, match='private command'):
        rehearsal.main()
    report = json.loads((output / 'report.json').read_text())
    assert report == {'kind': 'offline-search-compose-rehearsal/v2', 'cleanup_ok': None,
                      'passed': False, 'failure_type': 'RuntimeError'}


def test_resolved_configuration_accepts_safe_production_composition(tmp_path):
    rehearsal.validate_configuration(resolved_configuration(tmp_path), tmp_path)


@pytest.mark.parametrize('fault', ['ports', 'network', 'dependencies', 'environment', 'admin', 'grace', 'ocr', 'data'])
def test_resolved_configuration_rejects_unsafe_overrides(tmp_path, fault):
    configuration = resolved_configuration(tmp_path)
    services = configuration['services']
    if fault == 'ports':
        services['api']['ports'] = [{'target': 8000, 'published': '8000'}]
    elif fault == 'network':
        configuration['networks']['default']['internal'] = False
    elif fault == 'dependencies':
        del services['api']['depends_on']['rabbitmq']
    elif fault == 'environment':
        services['api']['volumes'][-1]['source'] = str(REPO / 'server/.env')
    elif fault == 'admin':
        services['admin']['read_only'] = False
    elif fault == 'grace':
        services['api']['stop_grace_period'] = '10s'
    elif fault == 'ocr':
        services['ocr']['volumes'][-1]['source'] = str(REPO)
    elif fault == 'data':
        services['api']['volumes'][0]['source'] = '/srv/live'
    with pytest.raises(RuntimeError):
        rehearsal.validate_configuration(configuration, tmp_path)


def test_redacted_report_removes_fixture_credentials_without_mutation():
    source = {'services': {'api': {'environment': {
        'AUTH_SECRET': 'secret', 'PRODUCT_BOOTSTRAP_PASSWORD': 'password',
        'ALIYUN_SMS_ACCESS_KEY_ID': 'id', 'ALIYUN_SMS_ACCESS_KEY_SECRET': 'key',
        'PRODUCT_BROKER_COOKIE': 'cookie', 'PRODUCT_INSTANCE': 'fixture',
    }}}}
    original = copy.deepcopy(source)
    redacted = rehearsal.redact_configuration(source)
    assert redacted['services']['api']['environment'] == {
        'AUTH_SECRET': '[redacted]', 'PRODUCT_BOOTSTRAP_PASSWORD': '[redacted]',
        'ALIYUN_SMS_ACCESS_KEY_ID': '[redacted]', 'ALIYUN_SMS_ACCESS_KEY_SECRET': '[redacted]',
        'PRODUCT_BROKER_COOKIE': '[redacted]', 'PRODUCT_INSTANCE': 'fixture',
    }
    assert source == original


def test_private_files_and_environment_parser(tmp_path):
    path = tmp_path / 'credentials.env'
    rehearsal.private_file(path, "PASSWORD='a b'\nEMPTY=''\n# comment\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert rehearsal.read_environment(path) == {'PASSWORD': 'a b', 'EMPTY': ''}
    with pytest.raises(FileExistsError):
        rehearsal.private_file(path, 'replacement')


@pytest.mark.parametrize('failure', ['copy', 'unsafe'])
def test_safe_source_removes_unstarted_container_after_failure(tmp_path, monkeypatch, failure):
    calls = []

    def fake_run(*command, **_kwargs):
        calls.append(command)
        if command[:2] == ('docker', 'cp'):
            if failure == 'copy':
                raise OSError('fixture copy failure')
            destination = Path(command[-1])
            destination.mkdir()
            (destination / '.env').write_text('must not be copied')

    monkeypatch.setattr(rehearsal, 'run', fake_run)
    monkeypatch.setattr(rehearsal.subprocess, 'run', lambda command, **_kwargs: calls.append(tuple(command)))
    with pytest.raises((OSError, RuntimeError)):
        rehearsal.safe_source('app-image', tmp_path, 'fixture')
    assert calls[0] == ('docker', 'create', '--pull=never', '--network=none', '--name', 'fixture-source', 'app-image')
    assert ('docker', 'rm', '-f', 'fixture-source') in calls
    assert not any(command[:2] in {('docker', 'start'), ('docker', 'exec')} for command in calls)


def test_rehearsal_failure_cleans_compose_project_and_keeps_original_error(tmp_path, monkeypatch):
    calls = []
    output = tmp_path / 'rehearsal'
    output.mkdir()
    configuration = resolved_configuration(output)

    def fake_run(*command, capture=False, env=None):
        calls.append(command)
        if command[:2] == ('git', '-C'):
            return 'fixture'
        if command[:2] == ('openssl', 'req'):
            (output / 'cert/shuxueshuo.com.key').write_text('fixture')
        if command[-1] == 'configure':
            directory = output / 'data/config'
            directory.mkdir()
            (directory / 'bootstrap.env').write_text("PRODUCT_BOOTSTRAP_PASSWORD='fixture'\n")
        if command[:2] == ('docker', 'compose'):
            assert env['PRODUCT_INSTANCE'] == 'search-rehearsal'
            assert 'SEARCH_GENERATION_ACCOUNT_DAILY' not in env
            assert 'PRODUCT_DATA_DIR' in env
            if 'config' in command:
                return json.dumps(configuration)
            if 'up' in command:
                raise RuntimeError('original startup failure')
        return '' if capture else None

    def fake_source(_image, directory, _identity):
        source = directory / 'source'
        (source / 'server').mkdir(parents=True)
        return source

    def fake_subprocess(command, **_kwargs):
        calls.append(tuple(command))
        return SimpleNamespace(returncode=1 if 'down' in command else 0, stdout='', stderr='fixture')

    monkeypatch.setenv('SEARCH_GENERATION_ACCOUNT_DAILY', '999')
    monkeypatch.setattr(rehearsal, 'run', fake_run)
    monkeypatch.setattr(rehearsal, 'image_info', lambda _name: images()['app'])
    monkeypatch.setattr(rehearsal, 'safe_source', fake_source)
    monkeypatch.setattr(rehearsal, 'prepare_fixtures', lambda directory: (directory / 'fixtures').mkdir())
    monkeypatch.setattr(rehearsal.subprocess, 'run', fake_subprocess)
    arguments = SimpleNamespace(**{name: name for name in images()})
    with pytest.raises(RuntimeError, match='original startup failure'):
        rehearsal.rehearse(arguments, output)
    compose_calls = [command for command in calls if command[:2] == ('docker', 'compose')]
    assert all(str(REPO / 'deploy/product' / name) in command for command in compose_calls
               for name in ('compose.yml', 'compose.server.yml', 'compose.app.yml'))
    assert any('down' in command and '--volumes' in command and '--remove-orphans' in command for command in compose_calls)
    for command in compose_calls:
        if 'config' in command:
            profiles = [command[index + 1] for index, item in enumerate(command) if item == '--profile']
            assert profiles == ['admin', 'fixture']
    report = json.loads((output / 'report.json').read_text())
    assert report['passed'] is False and report['cleanup_ok'] is False
    assert 'SEARCH_GENERATION_ACCOUNT_DAILY' not in (output / 'api.env').read_text()
    assert stat.S_IMODE((output / 'api.env').stat().st_mode) == 0o600
    assert stat.S_IMODE((output / 'cert/shuxueshuo.com.key').stat().st_mode) == 0o600
