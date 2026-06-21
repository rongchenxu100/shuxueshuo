import type {
  CreateTutorMessageRequest,
  TutorAction,
  TutorMessage,
  TutorSession,
} from "@/lib/contracts";
import { getCurrentUser } from "@/lib/user/current-user";

const sessionsById = new Map<string, TutorSession>();
const sessionIdsByProblemId = new Map<string, string>();
const messagesBySessionId = new Map<string, TutorMessage[]>();
let mockTutorRun = 0;

export function listTutorSessions(problemId: string): TutorSession[] {
  return [ensureTutorSession(problemId)];
}

export function ensureTutorSession(problemId: string): TutorSession {
  const existingSessionId = sessionIdsByProblemId.get(problemId);
  const existingSession = existingSessionId
    ? sessionsById.get(existingSessionId)
    : undefined;

  if (existingSession) {
    return existingSession;
  }

  const timestamp = new Date().toISOString();
  const user = getCurrentUser();
  const session: TutorSession = {
    createdAt: timestamp,
    id: `tutor_session_${problemId}_${user.id}`,
    problemId,
    title: "学习对话",
    updatedAt: timestamp,
    userId: user.id,
  };

  sessionsById.set(session.id, session);
  sessionIdsByProblemId.set(problemId, session.id);
  messagesBySessionId.set(session.id, []);

  return session;
}

export function getTutorMessages(sessionId: string): {
  messages: TutorMessage[];
  session: TutorSession;
} {
  const session = getTutorSession(sessionId);

  return {
    messages: messagesBySessionId.get(sessionId) ?? [],
    session,
  };
}

export function appendTutorMessage(
  sessionId: string,
  request: CreateTutorMessageRequest,
): {
  messages: TutorMessage[];
  session: TutorSession;
} {
  const session = getTutorSession(sessionId);
  const timestamp = new Date().toISOString();
  const idSuffix = `${Date.now()}_${mockTutorRun++}`;
  const userMessage: TutorMessage = {
    content: request.content,
    createdAt: timestamp,
    currentStepId: request.currentStepId,
    id: `tmsg_user_${idSuffix}`,
    role: "user",
    selectedTargetId: request.selectedTargetId,
    sessionId,
  };
  const assistantMessage: TutorMessage = {
    actions: buildTutorActions(request),
    content: buildTutorReply(request),
    createdAt: timestamp,
    currentStepId: request.currentStepId,
    id: `tmsg_assistant_${idSuffix}`,
    role: "assistant",
    selectedTargetId: request.selectedTargetId,
    sessionId,
  };
  const updatedSession: TutorSession = {
    ...session,
    currentStepId: request.currentStepId ?? session.currentStepId,
    updatedAt: timestamp,
  };
  const currentMessages = messagesBySessionId.get(sessionId) ?? [];
  const nextMessages = [...currentMessages, userMessage, assistantMessage];

  sessionsById.set(sessionId, updatedSession);
  messagesBySessionId.set(sessionId, nextMessages);

  return {
    messages: [userMessage, assistantMessage],
    session: updatedSession,
  };
}

function getTutorSession(sessionId: string): TutorSession {
  const session = sessionsById.get(sessionId);

  if (session) {
    return session;
  }

  const problemId = parseProblemIdFromSessionId(sessionId);
  const fallbackSession = ensureTutorSession(problemId);

  if (fallbackSession.id === sessionId) {
    return fallbackSession;
  }

  return fallbackSession;
}

function buildTutorReply(request: CreateTutorMessageRequest): string {
  if (request.selectedTargetId) {
    return "我会结合你选中的网页区域来解释。先看这个位置对应的条件，再把它和当前步骤的目标联系起来。";
  }

  return "这一步的关键是把复杂关系转化成更熟悉的结构。你可以先找等量关系，再看它如何服务于最终目标。";
}

function buildTutorActions(
  request: CreateTutorMessageRequest,
): TutorAction[] {
  const actions: TutorAction[] = [];

  if (request.currentStepId) {
    actions.push({
      stepId: request.currentStepId,
      type: "scroll_to_step",
    });
  }

  if (request.selectedTargetId) {
    actions.push({
      targetId: request.selectedTargetId,
      type: "highlight_target",
    });
  }

  actions.push({
    text: "先定位题目正在转化的对象，再看它是否能变成线段、面积或函数关系。",
    type: "show_hint",
  });

  return actions;
}

function parseProblemIdFromSessionId(sessionId: string): string {
  const prefix = "tutor_session_";
  const suffix = `_${getCurrentUser().id}`;

  if (sessionId.startsWith(prefix) && sessionId.endsWith(suffix)) {
    return sessionId.slice(prefix.length, -suffix.length);
  }

  return "problem_hongqiao_25";
}
