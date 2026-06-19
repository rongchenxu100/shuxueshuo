import { useEffect, useRef, useState } from "react";

import {
  createProblemFromText,
  startProblemUpload,
} from "@/lib/api/client";
import { parseUploadJobEvent } from "@/lib/api/sse";
import type { Problem, UploadJobProgressEvent } from "@/lib/contracts";

import {
  ConversationComposer,
  ImagePreviewDialog,
  SystemFeedback,
  UserPromptMessage,
  usePromptSnapshotRegistry,
} from "./composer";
import type {
  ProblemConversationAttempt,
  ProblemCreationScenario,
} from "./conversation-types";

export function NewProblemPanel({
  onProblemCreated,
  onUploadErrorChange,
  onUploadEventsChange,
}: {
  onProblemCreated: (
    problem: Problem,
    conversation: ProblemConversationAttempt[],
  ) => void;
  onUploadErrorChange: (message: string | null) => void;
  onUploadEventsChange: (events: UploadJobProgressEvent[]) => void;
}) {
  const [conversationState, setConversationState] =
    useState<"idle" | "submitting" | "failed">("idle");
  const [attempts, setAttempts] = useState<ProblemConversationAttempt[]>([]);
  const [previewImage, setPreviewImage] = useState<{
    alt: string;
    url: string;
  } | null>(null);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [scenario, setScenario] =
    useState<ProblemCreationScenario>("success");
  const [isCreatingText, setIsCreatingText] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const historyScrollRef = useRef<HTMLDivElement>(null);
  const nextAttemptIdRef = useRef(0);
  const attemptsRef = useRef<ProblemConversationAttempt[]>([]);
  const uploadEventsRef = useRef<UploadJobProgressEvent[]>([]);
  const uploadAbortControllerRef = useRef<AbortController | null>(null);
  const {
    createPromptSnapshot,
    retainConversationPreviews,
  } = usePromptSnapshotRegistry();

  useEffect(() => {
    return () => {
      uploadAbortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (conversationState === "idle") {
      return;
    }

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
  }, [attempts, conversationState]);

  async function handleSubmit() {
    if (!text.trim() && !file) {
      return;
    }

    const submittedText = text.trim();
    const submittedFile = file;
    const submittedScenario = scenario;
    const attemptId = nextAttemptIdRef.current + 1;
    nextAttemptIdRef.current = attemptId;
    const attempt: ProblemConversationAttempt = {
      error: null,
      events: [],
      id: attemptId,
      kind: submittedFile ? "upload" : "text",
      prompt: createPromptSnapshot(submittedText, submittedFile),
      status: "submitting",
    };

    setConversationState("submitting");
    setConversationAttempts([...attemptsRef.current, attempt]);
    onUploadEventsChange([]);
    onUploadErrorChange(null);
    clearComposer();

    if (submittedFile) {
      await handleUpload(attemptId, submittedFile, submittedScenario);
      return;
    }

    await handleCreateFromText(attemptId, submittedText, submittedScenario);
  }

  function clearComposer() {
    setText("");
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function updateAttempt(
    attemptId: number,
    patch: Partial<
      Pick<
        ProblemConversationAttempt,
        "error" | "events" | "status" | "systemMessage"
      >
    >,
  ) {
    const nextAttempts = attemptsRef.current.map((attempt) =>
      attempt.id === attemptId ? { ...attempt, ...patch } : attempt,
    );
    setConversationAttempts(nextAttempts);
    return nextAttempts;
  }

  function setConversationAttempts(
    nextAttempts: ProblemConversationAttempt[],
  ) {
    attemptsRef.current = nextAttempts;
    setAttempts(nextAttempts);
  }

  async function handleCreateFromText(
    attemptId: number,
    submittedText: string,
    submittedScenario: ProblemCreationScenario,
  ) {
    setIsCreatingText(true);

    try {
      const response = await createProblemFromText(
        { text: submittedText },
        { mockScenario: submittedScenario },
      );
      const conversation = updateAttempt(attemptId, {
        status: "completed",
        systemMessage: "已创建草稿题目",
      });
      retainConversationPreviews(conversation);
      onProblemCreated(response.problem, conversation);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "创建题目失败，请重试。";
      setConversationState("failed");
      updateAttempt(attemptId, { error: message, status: "failed" });
      onUploadErrorChange(message);
    } finally {
      setIsCreatingText(false);
    }
  }

  async function handleUpload(
    attemptId: number,
    submittedFile: File,
    submittedScenario: ProblemCreationScenario,
  ) {
    setIsUploading(true);
    uploadEventsRef.current = [];
    uploadAbortControllerRef.current?.abort();
    const abortController = new AbortController();
    uploadAbortControllerRef.current = abortController;

    const formData = new FormData();
    formData.append("file", submittedFile);
    formData.append("scenario", submittedScenario);

    try {
      const { streamUrl } = await startProblemUpload(formData);
      await subscribeUploadProgress(streamUrl, {
        onEvent: (event) => {
          const nextEvents = [...uploadEventsRef.current, event];
          uploadEventsRef.current = nextEvents;
          updateAttempt(attemptId, { events: nextEvents });
          onUploadEventsChange(nextEvents);

          if (event.type === "done") {
            const conversation = updateAttempt(attemptId, {
              status: "completed",
              systemMessage: "已完成上传生成",
            });
            retainConversationPreviews(conversation);
            onProblemCreated(event.problem, conversation);
          }

          if (event.type === "rejected") {
            setConversationState("failed");
            updateAttempt(attemptId, {
              error: event.message,
              status: "failed",
            });
            onUploadErrorChange(event.message);
          }

          if (event.type === "failed") {
            setConversationState("failed");
            updateAttempt(attemptId, {
              error: event.error.message,
              status: "failed",
            });
            onUploadErrorChange(event.error.message);
          }
        },
        signal: abortController.signal,
      });
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }

      const message = "上传进度连接中断，请重试";
      setConversationState("failed");
      updateAttempt(attemptId, { error: message, status: "failed" });
      onUploadErrorChange(message);
    } finally {
      if (uploadAbortControllerRef.current === abortController) {
        uploadAbortControllerRef.current = null;
        setIsUploading(false);
      }
    }
  }

  const isBusy = isCreatingText || isUploading;
  const canSubmit = Boolean(text.trim() || file) && !isBusy;
  const submitLabel = isUploading
    ? "上传中"
    : isCreatingText
      ? "正在创建"
      : file
        ? "上传并生成"
        : "创建题目";

  if (conversationState === "idle") {
    return (
      <div className="flex h-full items-center justify-center px-4 py-10">
        <div className="w-full max-w-4xl space-y-5">
          <h3 className="text-center text-2xl font-medium tracking-tight text-zinc-800">
            要创建什么题目？
          </h3>
          <ConversationComposer
            busy={isBusy}
            canSubmit={canSubmit}
            disabled={isBusy}
            file={file}
            fileInputRef={fileInputRef}
            placeholder="随心输入"
            scenario={scenario}
            setFile={setFile}
            setScenario={setScenario}
            setText={setText}
            showPreviewImage={setPreviewImage}
            showScenarioSelect
            submitLabel={submitLabel}
            text={text}
            onSubmit={handleSubmit}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-6"
        ref={historyScrollRef}
      >
        <div className="mx-auto max-w-4xl space-y-5">
          {attempts.map((attempt) => (
            <div className="space-y-5" key={attempt.id}>
              <UserPromptMessage
                prompt={attempt.prompt}
                showPreviewImage={setPreviewImage}
              />
              <SystemFeedback attempt={attempt} />
            </div>
          ))}
        </div>
      </div>
      <div className="pointer-events-none shrink-0 bg-gradient-to-t from-zinc-50 via-zinc-50 to-transparent px-4 pb-4 pt-4">
        <div className="pointer-events-auto mx-auto max-w-4xl">
          <ConversationComposer
            busy={isBusy}
            canSubmit={canSubmit}
            disabled={isBusy}
            file={file}
            fileInputRef={fileInputRef}
            placeholder="随心输入"
            scenario={scenario}
            setFile={setFile}
            setScenario={setScenario}
            setText={setText}
            showPreviewImage={setPreviewImage}
            showScenarioSelect
            submitLabel={submitLabel}
            text={text}
            onSubmit={handleSubmit}
          />
        </div>
      </div>
      {previewImage ? (
        <ImagePreviewDialog
          alt={previewImage.alt}
          src={previewImage.url}
          onClose={() => setPreviewImage(null)}
        />
      ) : null}
    </div>
  );
}

function subscribeUploadProgress(
  streamUrl: string,
  {
    onEvent,
    signal,
  }: {
    onEvent: (event: UploadJobProgressEvent) => void;
    signal?: AbortSignal;
  },
) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(createAbortError());
      return;
    }

    const source = new EventSource(streamUrl);
    let completed = false;

    function cleanup() {
      signal?.removeEventListener("abort", handleAbort);
    }

    function handleAbort() {
      source.close();
      cleanup();
      reject(createAbortError());
    }

    function handleTerminalEvent(event: MessageEvent, eventName: string) {
      const parsedEvent = parseUploadJobEvent(eventName, event.data);
      completed = true;
      onEvent(parsedEvent);
      source.close();
      cleanup();
      resolve();
    }

    signal?.addEventListener("abort", handleAbort, { once: true });
    source.addEventListener("progress", (event) => {
      onEvent(parseUploadJobEvent("progress", event.data));
    });
    source.addEventListener("done", (event) => {
      handleTerminalEvent(event, "done");
    });
    source.addEventListener("rejected", (event) => {
      handleTerminalEvent(event, "rejected");
    });
    source.addEventListener("failed", (event) => {
      handleTerminalEvent(event, "failed");
    });
    source.onerror = () => {
      source.close();
      cleanup();
      if (!completed) {
        reject(new Error("upload stream disconnected"));
      }
    };
  });
}

function createAbortError() {
  return new DOMException("Upload progress subscription aborted", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
