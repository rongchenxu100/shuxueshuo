"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createTutorMessage,
  createTutorSession,
  getTutorMessages,
  getTutorSessions,
} from "@/lib/api/client";
import type { TutorAction, TutorMessage, TutorSession } from "@/lib/contracts";

import { ConversationComposer } from "./composer";
import type { PreviewTargetSelectedMessage } from "./preview-bridge";

export type TutorPromptRequest = {
  content: string;
  id: number;
  target: PreviewTargetSelectedMessage;
};

export function TutorChat({
  externalPrompt,
  onAssistantActions,
  onExternalPromptHandled,
  onTargetClear,
  problemId,
  problemTitle,
  selectedTarget,
}: {
  externalPrompt?: TutorPromptRequest | null;
  onAssistantActions?: (actions: TutorAction[]) => void;
  onExternalPromptHandled?: (promptId: number) => void;
  onTargetClear?: () => void;
  problemId: string;
  problemTitle: string;
  selectedTarget?: PreviewTargetSelectedMessage | null;
}) {
  const [session, setSession] = useState<TutorSession | null>(null);
  const [messages, setMessages] = useState<TutorMessage[]>([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const historyScrollRef = useRef<HTMLDivElement>(null);
  const handledExternalPromptIdsRef = useRef<Set<number>>(new Set());
  const messagesRef = useRef<TutorMessage[]>(messages);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    let isActive = true;

    getTutorSessions(problemId)
      .then(async ({ sessions }) => {
        if (sessions[0]) {
          return { session: sessions[0] };
        }

        return createTutorSession(problemId);
      })
      .then(async ({ session: nextSession }) => {
        const { messages: nextMessages } = await getTutorMessages(
          nextSession.id,
        );

        if (!isActive) {
          return;
        }

        setSession(nextSession);
        messagesRef.current = nextMessages;
        setMessages(nextMessages);
      })
      .catch((error) => {
        if (isActive) {
          setSubmitError(
            error instanceof Error ? error.message : "学习对话加载失败。",
          );
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [problemId]);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => {
      const scrollContainer = historyScrollRef.current;
      if (!scrollContainer) {
        return;
      }

      scrollContainer.scrollTo({
        top: scrollContainer.scrollHeight,
      });
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [messages, submitError]);

  const submitTutorMessage = useCallback(async (
    submittedText: string,
    target: PreviewTargetSelectedMessage | null,
    options: { clearComposer?: boolean; restoreTextOnError?: boolean } = {},
  ) => {
    if (!submittedText || isSubmitting || !session) {
      return false;
    }

    const { clearComposer = true, restoreTextOnError = true } = options;
    const timestamp = new Date().toISOString();
    const optimisticMessage: TutorMessage = {
      content: submittedText,
      createdAt: timestamp,
      currentStepId: target?.stepId,
      id: `tmsg_local_${Date.now()}`,
      role: "user",
      selectedTargetId: target?.targetId,
      sessionId: session.id,
    };
    const previousMessages = messagesRef.current;

    setIsSubmitting(true);
    setSubmitError(null);
    if (clearComposer) {
      setText("");
    }
    const optimisticMessages = [...previousMessages, optimisticMessage];
    messagesRef.current = optimisticMessages;
    setMessages(optimisticMessages);

    try {
      const response = await createTutorMessage(session.id, {
        content: submittedText,
        currentStepId: target?.stepId,
        pageState: {
          scrollY: 0,
          sliderValues: {},
        },
        selectedTargetId: target?.targetId,
      });

      setSession(response.session);
      const nextMessages = [...previousMessages, ...response.messages];
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      const assistantActions = response.messages.flatMap(
        (message) => message.actions ?? [],
      );
      if (assistantActions.length) {
        onAssistantActions?.(assistantActions);
      }
      onTargetClear?.();
      return true;
    } catch (error) {
      messagesRef.current = previousMessages;
      setMessages(previousMessages);
      if (restoreTextOnError) {
        setText(submittedText);
      }
      setSubmitError(
        error instanceof Error ? error.message : "发送学习问题失败，请重试。",
      );
      return false;
    } finally {
      setIsSubmitting(false);
    }
  }, [
    isSubmitting,
    onAssistantActions,
    onTargetClear,
    session,
  ]);

  useEffect(() => {
    if (
      !externalPrompt ||
      handledExternalPromptIdsRef.current.has(externalPrompt.id) ||
      !session ||
      isSubmitting
    ) {
      return;
    }

    handledExternalPromptIdsRef.current.add(externalPrompt.id);
    void submitTutorMessage(externalPrompt.content, externalPrompt.target, {
      clearComposer: false,
      restoreTextOnError: true,
    }).finally(() => {
      onExternalPromptHandled?.(externalPrompt.id);
    });
  }, [
    externalPrompt,
    isSubmitting,
    onExternalPromptHandled,
    session,
    submitTutorMessage,
  ]);

  function handleSubmit() {
    void submitTutorMessage(text.trim(), selectedTarget ?? null);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-6"
        ref={historyScrollRef}
      >
        <div className="mx-auto max-w-4xl space-y-5">
          {isLoading ? (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-zinc-500">
              正在加载学习对话...
            </div>
          ) : messages.length ? (
            messages.map((message) => (
              <TutorMessageItem key={message.id} message={message} />
            ))
          ) : (
            <div className="flex min-h-[320px] items-center justify-center text-center">
              <div>
                <h3 className="text-lg font-medium text-zinc-800">
                  围绕这道题提问
                </h3>
                <p className="mt-2 text-sm text-zinc-500">
                  右侧预览可以作为上下文，点击步骤或图形后再提问。
                </p>
              </div>
            </div>
          )}
          {submitError ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {submitError}
            </p>
          ) : null}
        </div>
      </div>
      <div className="pointer-events-none shrink-0 bg-gradient-to-t from-zinc-50 via-zinc-50 to-transparent px-4 pb-4 pt-4">
        <div className="pointer-events-auto mx-auto max-w-4xl">
          {selectedTarget ? (
            <TargetContextCard
              selectedTarget={selectedTarget}
              onClear={onTargetClear}
            />
          ) : null}
          <ConversationComposer
            autoFocusOnReady
            busy={isSubmitting}
            canSubmit={Boolean(text.trim()) && !isSubmitting && Boolean(session)}
            disabled={isSubmitting || isLoading}
            file={file}
            fileInputRef={fileInputRef}
            placeholder={`向 ${problemTitle} 提问`}
            setFile={setFile}
            setText={setText}
            showAttachmentButton={false}
            showPreviewImage={() => undefined}
            submitLabel={isSubmitting ? "发送中" : "发送消息"}
            text={text}
            onSubmit={handleSubmit}
          />
        </div>
      </div>
    </div>
  );
}

function TutorMessageItem({ message }: { message: TutorMessage }) {
  const hintActions = message.actions?.filter(
    (action) => action.type === "show_hint",
  );

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="flex max-w-[82%] flex-col items-end gap-2">
          <div className="rounded-2xl bg-zinc-200 px-4 py-3 text-sm leading-6 text-zinc-900">
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.selectedTargetId ? (
              <div className="mt-3 rounded-xl bg-white/70 p-2 text-xs text-zinc-700">
                <div className="font-medium">来自网页预览</div>
                <div className="mt-1 truncate text-zinc-500">
                  {message.currentStepId
                    ? `${message.currentStepId} · ${message.selectedTargetId}`
                    : message.selectedTargetId}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[82%] space-y-2">
      <div className="text-sm font-medium text-zinc-500">
        {message.role === "assistant" ? "已回复" : "系统消息"}
      </div>
      <div className="whitespace-pre-wrap text-sm leading-6 text-zinc-800">
        {message.content}
      </div>
      {hintActions?.map((action, index) => (
        <div
          className="rounded-xl bg-teal-50 px-3 py-2 text-xs leading-5 text-teal-800"
          key={`${message.id}-hint-${index}`}
        >
          {action.text}
        </div>
      ))}
    </div>
  );
}

function TargetContextCard({
  onClear,
  selectedTarget,
}: {
  onClear?: () => void;
  selectedTarget: PreviewTargetSelectedMessage;
}) {
  return (
    <section className="mb-3 flex items-center justify-between gap-3 rounded-2xl border border-teal-200 bg-white/95 px-3 py-2 text-sm shadow-sm">
      <div className="min-w-0">
        <p className="font-medium text-zinc-800">正在询问网页区域</p>
        <p className="mt-0.5 truncate text-xs text-zinc-500">
          {selectedTarget.label} · {selectedTarget.targetId}
        </p>
      </div>
      <button
        className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-500 transition hover:bg-zinc-100"
        onClick={onClear}
        type="button"
      >
        清除
      </button>
    </section>
  );
}
