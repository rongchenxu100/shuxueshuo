from io import BytesIO

from PIL import Image

from shuxueshuo_server.review.store import ReviewStore
from shuxueshuo_server.review.versions import Versions
from shuxueshuo_server.review.problem_edit import editable, preview, install, load_contexts
from shuxueshuo_server.review.replay import extraction_store, restore_archive, ARCHIVE, archive_bytes
from shuxueshuo_server.solver.extraction.problem_solver_bundle import VerifiedSolverProblemBundleLoader
from _problem_planning_support import accepted_bundle_fixture


def test_human_revision_promotes_context_and_reloads_authenticated_bundle(tmp_path):
    initial, observation, accepted, source, verified, _, _ = accepted_bundle_fixture(tmp_path / 'fixture')
    store = ReviewStore(tmp_path / 'review')
    image = BytesIO()
    Image.new('RGB', (2, 2)).save(image, format='PNG')
    run = store.create(image.getvalue(), 'image/png', 'fixture.png')['id']
    store.claim()
    for stage, name, value in [('source', 'Source / selection / initial Context', initial), ('observation', 'Observation Context', observation), ('extraction', 'Extraction Context', accepted), ('extraction', 'VerifiedProblem', verified)]:
        store.add(run, stage, 'output', name, value.to_payload())
    store.add(run, 'extraction', 'output', ARCHIVE, archive_bytes(source.root), 'application/zip')
    restore_archive(store, run, 'extraction')
    versions = Versions(store)
    body = editable(store, run)
    body['domain']['root']['source_text'][0] += '（人工校对）'
    saved = preview(store, run, body, save=True)
    assert saved['ok']
    revision = versions.revision(saved['base_revision_id'])
    local = extraction_store(store.root / run / 'extraction-artifacts')
    install(store, run, revision, observation, (initial,), local)
    final, ancestors = load_contexts(store, run)
    bundle = VerifiedSolverProblemBundleLoader().load(final, local, ancestor_contexts=ancestors)
    assert bundle.verified_problem.parent_revision_id == verified.revision_id
    assert bundle.verified_problem.semantic_hash == revision['semantic_hash']
    assert final.manifest.producer == 'review_human_revision'
    assert not any(a['role'] == 'call' for a in store.get(run)['artifacts'])
