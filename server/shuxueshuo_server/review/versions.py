"""Subject/revision identity and transactional publication, separate from run history."""
import json
import time
from uuid import uuid4


class Conflict(ValueError):
    pass


class Versions:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS review_subjects(
                    id TEXT PRIMARY KEY, revision_id TEXT, latest_run_id TEXT, page_run_id TEXT);
                CREATE TABLE IF NOT EXISTS review_revisions(
                    id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_run_versions(
                    run_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, revision_id TEXT);
            ''')
            db.execute('BEGIN IMMEDIATE')
            docs = {row['id']: json.loads(row['doc']) for row in db.execute('SELECT id,doc FROM runs')}
            def migrate(run_id, seen=()):
                row = db.execute('SELECT * FROM review_run_versions WHERE run_id=?', (run_id,)).fetchone()
                if row: return row['subject_id']
                doc = docs[run_id]
                parent = doc.get('parent_run_id')
                subject = migrate(parent, (*seen, run_id)) if parent in docs and parent not in seen else run_id
                db.execute('INSERT OR IGNORE INTO review_subjects(id) VALUES(?)', (subject,))
                db.execute('INSERT INTO review_run_versions VALUES(?,?,NULL)', (run_id, subject))
                if doc['status'] != 'initializing':
                    db.execute('UPDATE review_subjects SET latest_run_id=? WHERE id=?', (run_id, subject))
                return subject
            for run_id in docs: migrate(run_id)

    def info(self, run_id):
        with self.store.connect() as db:
            row = db.execute('SELECT s.*,v.revision_id AS run_revision_id FROM review_run_versions v JOIN review_subjects s ON s.id=v.subject_id WHERE v.run_id=?', (run_id,)).fetchone()
        if row is None: raise KeyError(run_id)
        return dict(row)

    def revision(self, revision_id):
        if revision_id is None: return None
        with self.store.connect() as db:
            row = db.execute('SELECT doc FROM review_revisions WHERE id=?', (revision_id,)).fetchone()
        if row is None: raise KeyError(revision_id)
        return json.loads(row['doc'])

    def attach(self, run_id, parent=None, *, requested=True):
        # Constructor has already migrated this new run. Restore the parent's
        # draft identity; queuing and the latest request pointer share a transaction.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT subject_id FROM review_run_versions WHERE run_id=?', (run_id,)).fetchone()
            subject = row['subject_id']
            current = db.execute('SELECT revision_id FROM review_subjects WHERE id=?', (subject,)).fetchone()['revision_id']
            db.execute('UPDATE review_run_versions SET revision_id=? WHERE run_id=?', (current, run_id))
            if requested:
                db.execute('UPDATE review_subjects SET latest_run_id=? WHERE id=?', (run_id, subject))

    def capture(self, run_id):
        """Import an authentic extracted revision; never invent stage version evidence."""
        info = self.info(run_id)
        prior = self.revision(info['run_revision_id'])
        if prior and prior['kind'] == 'manual': return
        doc = self.store.get(run_id)
        ref = next((a for a in reversed(doc['artifacts']) if a['name'] == 'VerifiedProblem' and a['stage'] == 'extraction'), None)
        if not ref: return
        verified = json.loads(self.store.read(run_id, ref['id'])[1])
        if prior and prior['semantic_hash'] == verified['semantic_hash']: return
        revision_id = 'extracted:' + run_id
        record = {'id': revision_id, 'parent_id': info['run_revision_id'], 'source_run_id': run_id,
                  'domain': verified['graph'], 'verified': verified, 'semantic_hash': verified['semantic_hash'],
                  'kind': 'extracted', 'created_at': time.time()}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO review_revisions VALUES(?,?,?)', (revision_id, info['id'], json.dumps(record)))
            db.execute('UPDATE review_run_versions SET revision_id=? WHERE run_id=? AND revision_id IS ?', (revision_id, run_id, info['run_revision_id']))
            db.execute('UPDATE review_subjects SET revision_id=? WHERE id=? AND revision_id IS ? AND latest_run_id=?', (revision_id, info['id'], info['run_revision_id'], run_id))

    def save(self, run_id, base_revision_id, record):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            subject = db.execute('SELECT subject_id FROM review_run_versions WHERE run_id=?', (run_id,)).fetchone()['subject_id']
            current = db.execute('SELECT revision_id FROM review_subjects WHERE id=?', (subject,)).fetchone()['revision_id']
            if current != base_revision_id: raise Conflict('题意已被修改，请刷新后重新预览')
            prior = json.loads(db.execute('SELECT doc FROM review_revisions WHERE id=?', (current,)).fetchone()['doc'])
            if prior['semantic_hash'] == record['semantic_hash']: return prior
            record = {**record, 'id': uuid4().hex, 'parent_id': current, 'created_at': time.time()}
            db.execute('INSERT INTO review_revisions VALUES(?,?,?)', (record['id'], subject, json.dumps(record)))
            db.execute('UPDATE review_subjects SET revision_id=? WHERE id=?', (record['id'], subject))
            return record

    def enqueue(self, run_id, *, base_revision_id, target):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            link = db.execute('SELECT * FROM review_run_versions WHERE run_id=?', (run_id,)).fetchone()
            subject = db.execute('SELECT * FROM review_subjects WHERE id=?', (link['subject_id'],)).fetchone()
            if subject['revision_id'] != base_revision_id: raise Conflict('题意已变化，请刷新重建计划')
            doc = json.loads(db.execute('SELECT doc FROM runs WHERE id=?', (run_id,)).fetchone()['doc'])
            if doc['status'] != 'initializing': raise Conflict('构建已提交')
            doc.update(status='queued', target_dependencies=target, updated_at=time.time())
            db.execute('UPDATE runs SET doc=? WHERE id=?', (json.dumps(doc), run_id))
            db.execute('UPDATE review_run_versions SET revision_id=? WHERE run_id=?', (base_revision_id, run_id))
            db.execute('UPDATE review_subjects SET latest_run_id=? WHERE id=?', (run_id, link['subject_id']))
            self.store._event(db, doc)


def publish(db, doc):
    """Called inside the same transaction that commits a successful run."""
    if doc['status'] != 'succeeded' or not doc.get('target_dependencies'): return
    target = doc['target_dependencies']['stages']
    if any(not s.get('manifest') or any(s['manifest'][k] != target[s['id']][k] for k in ('resources', 'config')) for s in doc['stages']):
        return
    db.execute('''UPDATE review_subjects SET page_run_id=? WHERE latest_run_id=?
        AND EXISTS(SELECT 1 FROM review_run_versions v WHERE v.run_id=? AND v.subject_id=review_subjects.id
                   AND v.revision_id IS review_subjects.revision_id)''', (doc['id'], doc['id'], doc['id']))
