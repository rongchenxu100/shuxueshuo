"""Authoritative session with isolated route attempts and a chronological event log."""

import asyncio
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    InvalidAction,
    apply_action,
    current_node,
    fresh_state,
    route_complete,
    turn_context,
)
from .llm import Action


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=0)
    kind: Literal["ui", "text", "help"]
    action: Action | None = None
    text: str = Field(default="", max_length=2000)


class Conflict(Exception):
    pass


def load_lesson(lesson_id):
    # Only installed lesson filenames are loadable; user paths are never interpolated.
    lessons = {p.stem: p for p in (Path(__file__).parent / "lessons").glob("*.json")}
    return json.loads(lessons[lesson_id].read_text())


@dataclass
class Session:
    lesson: dict
    id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    state: dict = field(init=False)
    attempt_id: str = field(default_factory=lambda: uuid4().hex)
    archived_attempts: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    completed: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    responses: dict = field(default_factory=dict)
    updated: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        self.state = fresh_state(self.lesson)

    def current_messages(self):
        return [m for m in self.messages if m["attempt_id"] == self.attempt_id]

    def attempt_snapshot(self):
        return deepcopy(
            {
                "id": self.attempt_id,
                "route": self.state["method"],
                "status": "completed"
                if route_complete(self.lesson, self.state)
                else "learning",
                "state": self.state,
                "completed": self.completed,
                "accepted_evidence": self.evidence,
                "messages": self.current_messages(),
            }
        )

    def view(self):
        return deepcopy(
            {
                "session_id": self.id,
                "revision": self.revision,
                "lesson_id": self.lesson["id"],
                "lesson_version": self.lesson["version"],
                "attempt_id": self.attempt_id,
                "attempts": self.archived_attempts + [self.attempt_snapshot()],
                "state": self.state,
                "messages": self.messages,
                "completed": self.completed,
                "accepted_evidence": self.evidence,
                "lesson": {
                    "problem": self.lesson["problem"],
                    "methods": self.lesson["methods"],
                    "method_guidance": self.lesson["method_guidance"],
                    "routes": {
                        k: [
                            {f: n[f] for f in ("id", "title", "question")}
                            for n in r["nodes"]
                        ]
                        for k, r in self.lesson["routes"].items()
                    },
                },
            }
        )

    def validate_switch(self, action):
        if action.value not in self.lesson["routes"] or action.index is not None:
            raise InvalidAction("这条路径暂不可用，请选择题目提供的解题路径。")
        if len(self.archived_attempts) >= 20:
            raise InvalidAction("本次会话的路径尝试已达演示上限，请重新体验。")
        return action.value

    async def handle(self, event, tutor):
        async with self.lock:
            self.updated = time.monotonic()
            serialized = event.model_dump()
            if event.event_id in self.responses:
                previous, response = self.responses[event.event_id]
                if previous != serialized:
                    raise Conflict("同一事件编号不能用于不同操作。")
                return deepcopy(response)
            if event.revision != self.revision:
                raise Conflict("页面状态已更新，请按当前步骤继续。")
            if len(self.messages) >= 400:
                raise InvalidAction("本轮对话已达演示上限，请重新体验。")
            before = deepcopy(self.state)
            candidate = deepcopy(before)
            candidate.update(feedback="", hint=False)
            stage = before["active"]
            reply = None
            evidence = list(self.evidence)
            switch_to = None
            if event.kind == "ui":
                if event.action is None or event.text:
                    raise InvalidAction("缺少有效的页面操作。")
                try:
                    if event.action.kind == "switch_route":
                        switch_to = self.validate_switch(event.action)
                    else:
                        apply_action(candidate, event.action, self.lesson)
                        if candidate["method"] != before["method"]:
                            evidence = []
                except InvalidAction as exc:
                    candidate = deepcopy(before)
                    candidate["feedback"] = str(exc)
                    reply = str(exc)
                message = {
                    "role": "student",
                    "kind": "ui",
                    "action": event.action.model_dump(),
                }
            else:
                if event.action is not None or (
                    event.kind == "text" and not event.text.strip()
                ):
                    raise InvalidAction("请输入你的想法。")
                message = {
                    "role": "student",
                    "kind": event.kind,
                    "text": event.text if event.kind == "text" else "给点提示",
                }
                context = turn_context(self.lesson, before, self.evidence)
                context["attempt_id"] = self.attempt_id
                context["previous_attempts"] = [
                    {
                        "id": a["id"],
                        "route": a["route"],
                        "status": a["status"],
                        "completed_nodes": [n["node"] for n in a["completed"]],
                    }
                    for a in self.archived_attempts
                ]
                proposal = await tutor.respond(
                    lesson={
                        k: self.lesson[k]
                        for k in (
                            "id",
                            "version",
                            "problem",
                            "methods",
                            "method_guidance",
                        )
                    },
                    context=context,
                    completed=self.completed,
                    messages=[
                        m for m in self.current_messages() if m["stage"] == stage
                    ][-24:],
                    event=message,
                )
                reply = proposal.reply
                if event.kind == "text" and proposal.intent == "route_change":
                    try:
                        if not proposal.actions:
                            # Ambiguous target: explain available routes rather than promise a switch.
                            reply = (
                                "你想尝试哪条路径？可以选择"
                                + "、".join(
                                    r["label"] for r in self.lesson["routes"].values()
                                )
                                + "。"
                            )
                        else:
                            if (
                                len(proposal.actions) != 1
                                or proposal.actions[0].kind != "switch_route"
                                or proposal.evidence
                            ):
                                raise InvalidAction(
                                    "切换路径需要单独执行，不会同时提交新路径的答案。"
                                )
                            switch_to = self.validate_switch(proposal.actions[0])
                    except InvalidAction as exc:
                        reply = str(exc)
                elif event.kind == "text" and proposal.intent == "answer":
                    try:
                        if any(a.kind == "switch_route" for a in proposal.actions):
                            raise InvalidAction(
                                "route action requires route_change intent"
                            )
                        if sum(a.kind == "submit" for a in proposal.actions) > 1:
                            raise InvalidAction("multiple submissions")
                        for action in proposal.actions:
                            if candidate["active"] != stage:
                                raise InvalidAction("future node mutation")
                            if (
                                action.kind == "method"
                                and action.value != candidate["method"]
                            ):
                                evidence = []
                            if action.kind == "submit":
                                node = current_node(self.lesson, candidate)
                                if not node or not set(
                                    node["required_evidence"]
                                ).issubset(set(evidence + proposal.evidence)):
                                    raise InvalidAction("missing evidence")
                                for fill in node.get("text_autofill", []):
                                    apply_action(candidate, Action(**fill), self.lesson)
                            apply_action(candidate, action, self.lesson)
                        node = current_node(self.lesson, {**candidate, "active": stage})
                        if node:
                            evidence = sorted(
                                set(evidence + proposal.evidence)
                                & set(node["required_evidence"])
                            )
                            if candidate["active"] == stage and set(
                                node["required_evidence"]
                            ).issubset(evidence):
                                for fill in node.get("text_autofill", []):
                                    apply_action(candidate, Action(**fill), self.lesson)
                                apply_action(
                                    candidate, Action(kind="submit"), self.lesson
                                )
                    except InvalidAction:
                        candidate = deepcopy(before)
                        evidence = list(self.evidence)
                        reply = "这次表达还未能对应到当前可执行的操作，页面保持原来的状态。可以再说明你的数学关系，或选择页面上的路径和组件。"
                # Questions/help never mutate state, even if the model suggests an action.
            advanced = candidate["active"] > stage
            if reply and advanced:
                reply = current_node(self.lesson, {**candidate, "active": stage})[
                    "completion_reply"
                ]
            message.update(
                stage=stage,
                route=before["method"],
                attempt_id=self.attempt_id,
                revision=self.revision + 1,
            )
            self.messages.append(message)
            if switch_to is not None:
                archived = self.attempt_snapshot()
                if archived["status"] != "completed":
                    archived["status"] = "paused"
                self.archived_attempts.append(archived)
                self.attempt_id = uuid4().hex
                candidate = fresh_state(self.lesson)
                candidate["method"] = switch_to
                self.completed = []
                evidence = []
                reply = (
                    "好，我们再用“"
                    + self.lesson["routes"][switch_to]["label"]
                    + "”试一次。"
                )
                stage = 0
            if reply:
                self.messages.append(
                    {
                        "role": "assistant",
                        "kind": "text",
                        "text": reply,
                        "stage": stage,
                        "route": candidate["method"],
                        "attempt_id": self.attempt_id,
                        "revision": self.revision + 1,
                    }
                )
            if advanced:
                node = current_node(self.lesson, {**candidate, "active": stage})
                self.completed.append(
                    {
                        "stage": stage,
                        "route": candidate["method"],
                        "node": node["id"],
                        "evidence": node["required_evidence"],
                        "state": deepcopy(candidate),
                    }
                )
                evidence = []
            self.state = candidate
            self.evidence = evidence
            self.revision += 1
            response = self.view()
            self.responses[event.event_id] = (serialized, deepcopy(response))
            while len(self.responses) > 8:
                del self.responses[next(iter(self.responses))]
            return response


class Sessions:
    def __init__(self):
        self.items = {}

    def create(self, lesson_id):
        lesson = load_lesson(lesson_id)
        now = time.monotonic()
        for key, value in list(self.items.items()):
            if now - value.updated > 7200 and not value.lock.locked():
                del self.items[key]
        if len(self.items) >= 200:
            raise InvalidAction("演示会话已满，请稍后再试。")
        session = Session(lesson)
        self.items[session.id] = session
        return session

    def get(self, session_id):
        session = self.items[session_id]
        if time.monotonic() - session.updated > 7200:
            del self.items[session_id]
            raise KeyError(session_id)
        return session
