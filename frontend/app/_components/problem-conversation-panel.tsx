import { useEffect, useRef, useState } from "react";

import { createProblemMessage } from "@/lib/api/client";
import type { Problem, ProblemMessage, WebAnnotation } from "@/lib/contracts";

import {
  ConversationComposer,
  ImagePreviewDialog,
  ProblemMessageItem,
} from "./composer";

export function ProblemConversationPanel({
  annotations,
  conversation,
  onConversationChange,
  onPendingAnnotationRemove,
  onPendingAnnotationsCommitted,
  onProblemEdited,
  pendingAnnotationIds,
  problem,
}: {
  annotations: WebAnnotation[];
  conversation: ProblemMessage[];
  onConversationChange: (
    problemId: string,
    conversation: ProblemMessage[],
  ) => void;
  onPendingAnnotationRemove: (
    problemId: string,
    annotationId: string,
  ) => void;
  onPendingAnnotationsCommitted: (problemId: string) => void;
  onProblemEdited: (problem: Problem) => void;
  pendingAnnotationIds: string[];
  problem: Problem;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewImage, setPreviewImage] = useState<{
    alt: string;
    url: string;
  } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const historyScrollRef = useRef<HTMLDivElement>(null);
  const pendingAnnotations = pendingAnnotationIds.flatMap((annotationId) => {
    const annotation = annotations.find((item) => item.id === annotationId);

    return annotation ? [annotation] : [];
  });

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
  }, [conversation, submitError]);

  async function handleSubmit() {
    const submittedText = text.trim();
    const hasPendingAnnotations = pendingAnnotations.length > 0;
    const messageContent = submittedText || "处理这些网页注释";

    if ((!submittedText && !hasPendingAnnotations) || isSubmitting) {
      return;
    }

    const timestamp = new Date().toISOString();
    const optimisticMessage: ProblemMessage = {
      content: messageContent,
      annotations: pendingAnnotations.length ? pendingAnnotations : undefined,
      createdAt: timestamp,
      id: `msg_local_${Date.now()}`,
      problemId: problem.id,
      role: "user",
    };
    const previousConversation = conversation;

    setIsSubmitting(true);
    setSubmitError(null);
    setText("");
    setFile(null);
    onConversationChange(problem.id, [
      ...previousConversation,
      optimisticMessage,
    ]);

    try {
      const response = await createProblemMessage(problem.id, {
        annotationIds: pendingAnnotationIds,
        content: messageContent,
      });
      onConversationChange(problem.id, [
        ...previousConversation,
        ...response.messages,
      ]);
      onProblemEdited({
        ...problem,
        autosavedAt: response.problem.autosavedAt,
        previewUrl: response.preview.previewUrl,
        previewVersion: response.preview.previewVersion,
        status: response.problem.status,
        updatedAt: response.problem.updatedAt,
      });
      onPendingAnnotationsCommitted(problem.id);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "发送修改请求失败，请重试。";
      onConversationChange(problem.id, previousConversation);
      setText(submittedText);
      setSubmitError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-6"
        ref={historyScrollRef}
      >
        <div className="mx-auto max-w-4xl space-y-5">
          {conversation.length ? (
            conversation.map((message) => (
              <ProblemMessageItem
                key={message.id}
                message={message}
                showPreviewImage={setPreviewImage}
              />
            ))
          ) : (
            <div className="flex min-h-[320px] items-center justify-center text-center">
              <div>
                <h3 className="text-lg font-medium text-zinc-800">
                  继续完善这道题
                </h3>
                <p className="mt-2 text-sm text-zinc-500">
                  题目内容在右侧预览，中间保留为对话和修改记录。
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
          {pendingAnnotations.length ? (
            <PendingAnnotationsCard
              annotations={pendingAnnotations}
              onRemove={(annotationId) =>
                onPendingAnnotationRemove(problem.id, annotationId)
              }
            />
          ) : null}
          <ConversationComposer
            autoFocusOnReady
            busy={isSubmitting}
            canSubmit={
              Boolean(text.trim() || pendingAnnotations.length) &&
              !isSubmitting
            }
            disabled={isSubmitting}
            file={file}
            fileInputRef={fileInputRef}
            placeholder="继续输入修改要求"
            setFile={setFile}
            setText={setText}
            showAttachmentButton={false}
            showPreviewImage={setPreviewImage}
            submitLabel={isSubmitting ? "发送中" : "发送消息"}
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

function PendingAnnotationsCard({
  annotations,
  onRemove,
}: {
  annotations: WebAnnotation[];
  onRemove: (annotationId: string) => void;
}) {
  return (
    <section className="mb-3 rounded-2xl border border-teal-200 bg-white/95 p-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium text-zinc-800">
          来自网页预览的 {annotations.length} 条注释
        </h3>
      </div>
      <div className="mt-2 space-y-2">
        {annotations.map((annotation, index) => (
          <div
            className="flex items-start gap-2 rounded-xl bg-zinc-50 px-3 py-2 text-sm"
            key={annotation.id}
          >
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-teal-600 text-xs font-medium text-white">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-zinc-800">
                {annotation.label}
              </div>
              <p className="mt-0.5 line-clamp-2 text-zinc-600">
                {annotation.comment}
              </p>
            </div>
            <button
              className="shrink-0 rounded-md px-2 py-1 text-xs text-zinc-500 transition hover:bg-white hover:text-zinc-900"
              onClick={() => onRemove(annotation.id)}
              type="button"
            >
              移除
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
