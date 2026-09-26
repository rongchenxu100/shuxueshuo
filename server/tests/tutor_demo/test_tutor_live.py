"""Opt-in, paid DeepSeek smoke: RUN_TUTOR_LIVE=1 uv run pytest tests/tutor_demo/test_tutor_live.py -q -s."""

import asyncio
import os

import pytest

from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live-test opt-in required"
)
def test_deepseek_elimination_and_question():
    async def run():
        class RecordingTutor(DeepSeekTutor):
            async def respond(self, **kwargs):
                self.last_proposal = await super().respond(**kwargs)
                return self.last_proposal

        tutor = RecordingTutor()
        session = Session(load_lesson("q01"))
        cases = [
            ("是不是可以用条件消元法？我还不知道怎么写。", 0),
            ("用条件消元法，m=2-n，保留n。", 1),
            ("把它看成开口向下的二次函数，用顶点求最大值。", 2),
            ("满足，m=n=1都是正数，而且1+1=2。", 3),
        ]
        try:
            for text, expected in cases:
                result = await session.handle(
                    Event(
                        event_id=str(session.revision),
                        revision=session.revision,
                        kind="text",
                        text=text,
                    ),
                    tutor,
                )
                print(result["state"]["active"], result["messages"][-1]["text"])
                assert result["state"]["active"] == expected, (
                    tutor.last_proposal.model_dump()
                )
            assert session.state["elimination"] == {
                "variable": "n",
                "technique": "vertex",
                "feasible": "yes",
            }
            previous_attempt = session.attempt_id
            result = await session.handle(
                Event(
                    event_id="switch-live",
                    revision=session.revision,
                    kind="text",
                    text="想让我们试试那个直接用基本不等式的方法吧",
                ),
                tutor,
            )
            assert result["attempt_id"] != previous_attempt
            assert (
                result["state"]["method"] == "direct" and result["state"]["active"] == 0
            )
            assert result["attempts"][0]["status"] == "completed"
            assert result["completed"] == []
            print("switched:", result["messages"][-1]["text"])
            for text, expected in [
                ("两个正数和为2，要求积的最大值，是定和求积。", 1),
                ("m+n≥2√(mn)", 2),
                ("m=n时取等", 3),
            ]:
                result = await session.handle(
                    Event(
                        event_id=str(session.revision),
                        revision=session.revision,
                        kind="text",
                        text=text,
                    ),
                    tutor,
                )
                print(
                    "new attempt:",
                    result["state"]["active"],
                    result["messages"][-1]["text"],
                )
                assert result["state"]["active"] == expected, (
                    tutor.last_proposal.model_dump()
                )
        finally:
            await tutor.close()

    asyncio.run(run())
