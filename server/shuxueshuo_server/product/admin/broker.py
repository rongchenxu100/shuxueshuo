"""Dedicated native RabbitMQ node; never use brew services or a default node."""
from pathlib import Path
import subprocess
import time

from ..errors import ProductError


def environment(runtime):
    root = runtime.settings.root
    values = runtime.values
    return {**runtime.environment(), 'RABBITMQ_NODENAME': 'shuxueshuo_' + runtime.settings.instance.replace('-', '_') + '@localhost',
        'RABBITMQ_MNESIA_BASE': str(root / 'rabbitmq/mnesia'), 'RABBITMQ_LOG_BASE': str(root / 'logs/rabbitmq'),
        'RABBITMQ_CONFIG_FILE': str(root / 'config/rabbitmq.conf'), 'CONF_ENV_FILE': str(root / 'config/rabbitmq-env.conf'),
        'RABBITMQ_CONF_ENV_FILE': str(root / 'config/rabbitmq-env.conf'),
        'RABBITMQ_ENABLED_PLUGINS_FILE': str(root / 'config/rabbitmq-plugins'),
        'RABBITMQ_ERLANG_COOKIE': values['BROKER_COOKIE'], 'RABBITMQ_NODE_PORT': values['BROKER_PORT'],
        'RABBITMQ_DIST_PORT': str(int(values['BROKER_PORT']) + 20000),
        'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS': '-kernel inet_dist_use_interface {127,0,0,1}',
        'RABBITMQ_PID_FILE': str(root / 'rabbitmq/node.pid')}


def command(runtime, tool, *args, timeout=30):
    return subprocess.run([str(Path(runtime.values['RABBITMQ_BIN']) / tool), *args], env=environment(runtime),
                          capture_output=True, text=True, timeout=timeout)


def status(runtime):
    try: return command(runtime, 'rabbitmq-diagnostics', '-q', 'ping', timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False


def configure(runtime):
    root = runtime.settings.root
    for path in ('rabbitmq', 'logs/rabbitmq'): (root / path).mkdir(parents=True, exist_ok=True, mode=0o700)
    v = runtime.values
    config = {'listeners.tcp.1': f"127.0.0.1:{v['BROKER_PORT']}", 'default_user': v['BROKER_USER'],
        'default_pass': v['BROKER_PASSWORD'], 'default_vhost': v['BROKER_VHOST'],
        'consumer_timeout': '7200000', 'log.console': 'false'}
    for filename, content in (('rabbitmq.conf', ''.join(f'{k} = {value}\n' for k, value in config.items())),
                              ('rabbitmq-env.conf', ''), ('rabbitmq-plugins', '[].\n')):
        path = root / 'config' / filename
        if path.exists():
            if path.read_text() != content: raise ProductError('broker.config_conflict')
        else:
            with path.open('x') as f: f.write(content)
            path.chmod(0o600)


def start(runtime):
    configure(runtime)
    if status(runtime): return
    for port in (int(runtime.values['BROKER_PORT']), int(runtime.values['BROKER_PORT']) + 20000):
        import socket
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1', port))
            except OSError: raise ProductError('broker.port_in_use') from None
    result = command(runtime, 'rabbitmq-server', '-detached')
    if result.returncode: raise ProductError('broker.start_failed')
    for _ in range(15):
        if status(runtime): return
        time.sleep(1)
    raise ProductError('broker.start_timeout')


def stop(runtime):
    if status(runtime) and command(runtime, 'rabbitmqctl', 'stop').returncode:
        raise ProductError('broker.stop_failed')
