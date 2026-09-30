"""Real tutor dialogue replay for reciprocal practice lessons (explicit opt-in)."""
import json
import re

from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson
from .test_local_practice import operation, pending


async def replay(lesson_id, turns):
    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    session, tutor = Session(load_lesson(lesson_id)), RecordingTutor()
    try:
        for i, (text, active, question, operations, evidence) in enumerate(turns):
            # Apply the same local UI operations before asking the real tutor.
            for j, op in enumerate(pending([operation(*op) for op in operations])):
                await session.handle(Event(**{**op, 'event_id': f'ui-{i}-{j}'},
                                           kind='ui', revision=session.revision), tutor)
            before = session.view()['state']
            previous_evidence = set(session.view()['accepted_evidence'])
            view = await session.handle(Event(
                event_id=f'live-{i}', kind='text', text=text, revision=session.revision,
                lesson_version=1,
            ), tutor)
            proposal = tutor.proposal
            record = {'lesson': lesson_id, 'turn': i+1, 'student': text,
                      'active': view['state']['active'], 'reply': view['messages'][-1]['text'],
                      'model_reply': proposal.reply, 'evidence': proposal.evidence,
                      'actions': [a.model_dump() for a in proposal.actions]}
            print(json.dumps(record, ensure_ascii=False), flush=True)
            assert view['state']['active'] == active, record
            assert not re.search('未能对应到当前可执行的操作|契约|reciprocal_coefficient|equal_terms', record['reply']), record
            if question:
                assert not proposal.evidence and not proposal.actions, record
                if before:
                    for key in ('active', 'pairs', 'choices', 'swapped'):
                        assert view['state'][key] == before[key], record
            if evidence == []:
                assert not proposal.actions, record
            if evidence is not None:
                assert set(evidence) <= set(proposal.evidence) <= set(evidence) | previous_evidence, record
        return view
    finally:
        await tutor.close()
