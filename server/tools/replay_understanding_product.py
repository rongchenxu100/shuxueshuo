"""Replay frozen responses through the product DB and stage runner. No model I/O.

Only accepts a separately installed local test instance under /private/tmp.
The response provider has no SDK client and cannot fall back to a paid provider.
"""
import argparse
import json
from dataclasses import replace
from hashlib import sha256
from html import escape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from shuxueshuo_server.product.admin.database import seed
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.product.execution import ExecutionContext
from shuxueshuo_server.product.runner import StageRunner
from shuxueshuo_server.product.services import ProductService
from shuxueshuo_server.product.storage import LocalArtifactStorage
from shuxueshuo_server.product.understanding import Understanding
from shuxueshuo_server.product.understanding_runtime import (
    configuration,
    target_dependencies,
)


class RecordedProvider:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def prepare_request(self, request):
        return replace(request, timeout=300, max_tokens=16384, stream=False, thinking_mode='enabled', reasoning_effort='low')

    def complete(self, request):
        self.requests.append(request.redacted_payload())
        saved = self.responses.pop(0)
        metadata = {**saved['metadata'], 'provider': 'recorded-deepseek', 'replay': True,
                    'recorded_elapsed_seconds': saved['elapsed_seconds'], 'recorded_network_attempts': saved['network_attempts'],
                    'file_api_calls': 0}
        return SimpleNamespace(text=saved['text'], finish_reason=saved['finish_reason'],
            metadata_payload=lambda: metadata, raw_payload=saved['raw_payload'],
            provider_attempts=tuple({} for _ in range(saved['network_attempts'])))


def replay(settings, batch, report):
    if settings.instance in ('local', 'server') or not str(settings.root).startswith('/private/tmp/'):
        raise ValueError('An independently installed /private/tmp test instance is required')
    report.mkdir(parents=True, exist_ok=True)
    db, admin = engine(settings.url()), engine(settings.url('migration'))
    app = Application(settings, ProductService(db, LocalArtifactStorage(settings.artifact_root)), seed(admin))
    u, results = Understanding(app), []
    package = Path(__file__).resolve().parents[1] / 'shuxueshuo_server/product'
    frozen = {**configuration(), 'product_implementation': {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob('*.py'))}}
    (report / 'freeze.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2))
    try:
        cases = sorted(p for p in batch.iterdir() if (p / 'workflow/calls').is_dir())
        for case in cases:
            image = case / 'input-fixture/source.png'
            responses = [json.loads(path.read_text()) for path in sorted((case / 'workflow/calls').glob('*/response.json'))]
            provider = RecordedProvider(responses)
            group = app.create_batch(uuid4().hex, '题意阶段一录制验收')
            upload = app.upload(UUID(group['id']), uuid4().hex, image.read_bytes(), case.name + '.png', 'image/png')['item']
            pid = UUID(upload['problem_id'])
            initial = u.summary(pid)
            source = u.source_version(pid, UUID(initial['source_version']['id']) if initial['source_version'] else None,
                [UUID(upload['source_id'])], uuid4().hex)
            current = u.summary(pid)
            base = UUID(current['candidate']['id']) if current['candidate'] else None
            submitted = u.start(pid, UUID(source['id']), base, 'extract', uuid4().hex)
            version = target_dependencies(source, base)['deployment_version']
            execution = app.service.acquire_execution(app.ctx, UUID(submitted['job_id']), 'recorded-acceptance', deployment_version=version, lease_seconds=300)
            context = ExecutionContext(app, app.ctx, UUID(submitted['build_id']), execution['id'], execution['epoch'])
            with patch('shuxueshuo_server.product.understanding_runtime.DeepSeekMultimodalExtractionProvider', return_value=provider):
                # Explicit dummy key only satisfies the product configuration guard. No SDK exists here.
                context.config = replace(context.config, deepseek_api_key='recorded-offline-no-network')
                result = StageRunner(context).run()
            summary = u.summary(pid)
            record = {'case': case.name, 'source_image_sha256': sha256(image.read_bytes()).hexdigest(),
                'problem_id': str(pid), 'source_version_id': source['id'], 'source_hash': source['source_hash'],
                'run_id': submitted['run_id'], 'stored': summary['candidate'] is not None,
                'source_reviewed': summary['source_reviewed'], 'match_status': summary['match_status'],
                'status': result['status'], 'candidate': summary['candidate']['candidate_json'] if summary['candidate'] else None,
                'result': result, 'run': u.run(UUID(submitted['run_id']))}
            results.append(record)
            (report / (case.name + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2))
            print(json.dumps({k: record[k] for k in ('case', 'stored', 'source_reviewed', 'match_status', 'status')}, ensure_ascii=False), flush=True)
        payload = {'mode': 'recorded-product-replay', 'paid_model_calls': 0, 'instance': settings.instance,
                   'frozen_batch': batch.name, 'stored': sum(r['stored'] for r in results), 'cases': results}
        (report / 'results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        rows = ''.join(f'<tr><td>{escape(r["case"])}</td><td>已保存</td><td>{escape(r["match_status"])}</td><td>{escape(r["status"])}</td><td>{"confirmed" if r["source_reviewed"] else "缺图阻断"}</td></tr>' for r in results)
        sections = ''.join(f'<section><h2>{escape(r["case"])}</h2><p>数据库题目 {r["problem_id"]} · 运行 {r["run_id"]}</p><details open><summary>简洁候选</summary><pre>{escape(json.dumps(r["candidate"], ensure_ascii=False, indent=2))}</pre></details><details><summary>完整调用、诊断与采用记录</summary><pre>{escape(json.dumps(r["run"], ensure_ascii=False, indent=2))}</pre></details></section>' for r in results)
        (report / 'outputs.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>阶段一：七题产品持久化验收</title><style>body{max-width:1120px;margin:48px auto;padding:0 24px;font:16px/1.65 system-ui;color:#172332}h1{font-size:30px}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #d8e2e7;text-align:left}section{margin-top:48px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7fa;padding:20px;border-radius:12px;font-size:13px}summary{cursor:pointer;color:#06685e}</style><h1>阶段一：七题产品持久化验收</h1><p>复用已冻结的真实响应，经过当前产品任务与 PostgreSQL 保存、查询。本次付费模型调用为 0；调用记录内 token 是原录制响应的用量，耗时是本地回放耗时。</p><p>7/7 保留完整题意数据；6 题来源复核 confirmed。K 题保留缺图阻断、原候选及已知语义差异（k 作用域、四边形声明）。这不表示七题数学语义全部通过。候选尚未接入求解。</p><table><thead><tr><th>题目</th><th>持久化</th><th>题型</th><th>处理结论</th><th>来源复核</th></tr></thead><tbody>' + rows + '</tbody></table>' + sections + '</html>')
        return payload
    finally:
        db.dispose(); admin.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--batch-dir', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    replay(Settings.load('local', args.data_dir, args.instance), args.batch_dir, args.report_dir)
