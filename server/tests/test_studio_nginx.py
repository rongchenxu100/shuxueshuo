"""Opt-in real Nginx compression test, isolated from deployed services."""
import gzip
import http.client
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

import pytest


@pytest.mark.skipif(os.environ.get('RUN_NGINX_INTEGRATION') != '1', reason='requires Docker and nginx:1.28-alpine')
def test_studio_page_location_gzip_and_conditional_forwarding(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    production = (repo / 'deploy/nginx/studio.shuxueshuo.com.conf').read_text().split('# HTTPS：', 1)[1]
    production = 'server {' + production.split('server {', 1)[1]
    production = production.replace('listen 443 ssl http2;', 'listen 8080;').replace('listen [::]:443 ssl http2;', '')
    production = re.sub(r'^\s*ssl_(?:certificate|certificate_key|protocols)\s+.*?;', '', production, flags=re.M)
    body = b'<!doctype html><html><body>' + b'<p>Geometry lesson content and scripts.</p>' * 15000 + b'</body></html>'
    page = tmp_path / 'api/product/v1/pages/test/index.html'
    page.parent.mkdir(parents=True)
    page.write_bytes(body)
    # Real nginx upstream supplies a page/validator; product authorization and
    # its weak ETag are tested separately against PostgreSQL in test_page_cache.
    config = 'events {}\nhttp { include /etc/nginx/mime.types; access_log off; server { listen 8000; root /fixtures; add_header Cache-Control "private, no-cache"; }\n' + production + '\n}'
    (tmp_path / 'nginx.conf').write_text(config)
    name = 'studio-gzip-test-' + uuid4().hex
    def docker(*args):
        return subprocess.run(['docker', *args], capture_output=True, text=True, check=True, timeout=30).stdout
    started = False
    try:
        docker('run', '--detach', '--name', name, '--publish', '127.0.0.1::8080',
               '--mount', f'type=bind,src={tmp_path},dst=/fixtures,readonly',
               'nginx:1.28-alpine', 'nginx', '-c', '/fixtures/nginx.conf', '-g', 'daemon off;')
        started = True
        docker('exec', name, 'nginx', '-t', '-c', '/fixtures/nginx.conf')
        port = int(docker('port', name, '8080/tcp').strip().rsplit(':', 1)[1])
        def get(headers):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            try:
                connection.request('GET', '/api/product/v1/pages/test/index.html', headers=headers)
                response = connection.getresponse()
                return response.status, dict((k.lower(), v) for k, v in response.getheaders()), response.read()
            finally: connection.close()
        for n in range(20):
            try: plain = get({'Accept-Encoding': 'identity'}); break
            except (ConnectionError, http.client.HTTPException):
                if n == 19: raise
                time.sleep(.1)
        assert plain[0] == 200 and plain[2] == body
        compressed = get({'Accept-Encoding': 'gzip'})
        assert compressed[0] == 200 and compressed[1]['content-encoding'] == 'gzip'
        assert gzip.decompress(compressed[2]) == body and len(compressed[2]) < len(body) / 3
        assert compressed[1]['cache-control'] == 'private, no-cache'
        assert 'Accept-Encoding' in compressed[1]['vary']
        assert compressed[1]['etag'].removeprefix('W/') == plain[1]['etag'].removeprefix('W/')
        cached = get({'Accept-Encoding': 'gzip', 'If-None-Match': compressed[1]['etag']})
        assert cached[0] == 304 and cached[2] == b''
        assert cached[1]['cache-control'] == 'private, no-cache'
    finally:
        if started: docker('rm', '--force', name)


@pytest.mark.skipif(os.environ.get('RUN_NGINX_INTEGRATION') != '1', reason='requires Docker and nginx:1.28-alpine')
@pytest.mark.parametrize('via_cdn', [False, True], ids=['https-static', 'http-cdn-origin'])
def test_main_site_static_catalog_gzip_and_etag(tmp_path, via_cdn):
    repo = Path(__file__).resolve().parents[2]
    template = (repo / 'deploy/nginx/shuxueshuo.conf').read_text()
    # Test each deployed location; TLS certificates are unrelated to gzip.
    blocks = template.split('\nserver {')
    production = 'server {' + (blocks[1] if via_cdn else blocks[2].split('# -----', 1)[0])
    production = re.sub(r'listen (?:80|443 ssl http2);', 'listen 8080;', production)
    production = re.sub(r'listen \[::\]:(?:80|443 ssl http2);', '', production)
    production = re.sub(r'^\s*ssl_(?:certificate|certificate_key|protocols)\s+.*?;', '', production, flags=re.M)
    production = production.replace('/home/ronghao/code/shuxueshuo/site', '/fixtures/site')
    paths = ['assets/js/senior-high-catalog-data.js', 'data/senior-high-catalog.json']
    bodies = {}
    for path in paths:
        body = (repo / 'site' / path).read_bytes()
        target = tmp_path / 'site' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        bodies[path] = body
    (tmp_path / 'nginx.conf').write_text('events {}\nhttp { include /etc/nginx/mime.types; access_log off;\n' + production + '\n}')
    name = 'main-site-gzip-test-' + uuid4().hex

    def docker(*args):
        return subprocess.run(['docker', *args], capture_output=True, text=True, check=True, timeout=30).stdout

    started = False
    try:
        docker('run', '--detach', '--name', name, '--publish', '127.0.0.1::8080',
               '--mount', f'type=bind,src={tmp_path},dst=/fixtures,readonly',
               'nginx:1.28-alpine', 'nginx', '-c', '/fixtures/nginx.conf', '-g', 'daemon off;')
        started = True
        docker('exec', name, 'nginx', '-t', '-c', '/fixtures/nginx.conf')
        port = int(docker('port', name, '8080/tcp').strip().rsplit(':', 1)[1])

        def get(path, headers):
            if via_cdn:
                headers = {**headers, 'X-Forwarded-Proto': 'https', 'Via': '1.1 test-cdn'}
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            try:
                connection.request('GET', '/' + path, headers=headers)
                response = connection.getresponse()
                return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
            finally:
                connection.close()

        for path, body in bodies.items():
            for attempt in range(20):
                try:
                    plain = get(path, {'Accept-Encoding': 'identity'})
                    break
                except (ConnectionError, http.client.HTTPException):
                    if attempt == 19:
                        raise
                    time.sleep(.1)
            assert plain[0] == 200 and plain[2] == body
            compressed = get(path, {'Accept-Encoding': 'gzip'})
            assert compressed[0] == 200 and compressed[1]['content-encoding'] == 'gzip'
            assert gzip.decompress(compressed[2]) == body
            assert len(compressed[2]) < len(body) / 3
            assert 'Accept-Encoding' in compressed[1]['vary']
            assert compressed[1]['x-content-type-options'] == 'nosniff'
            assert compressed[1]['x-frame-options'] == 'SAMEORIGIN'
            assert compressed[1]['etag'].removeprefix('W/') == plain[1]['etag']
            cached = get(path, {'Accept-Encoding': 'gzip', 'If-None-Match': compressed[1]['etag']})
            assert cached[0] == 304 and cached[2] == b''
    finally:
        if started:
            docker('rm', '--force', name)
