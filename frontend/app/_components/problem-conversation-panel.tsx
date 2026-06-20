import { useEffect, useRef, useState } from "react";

import { createProblemMessage } from "@/lib/api/client";
import type { Problem, ProblemMessage } from "@/lib/contracts";

import {
  ConversationComposer,
  ImagePreviewDialog,
  ProblemMessageItem,
} from "./composer";

export function ProblemConversationPanel({
  conversation,
  onConversationChange,
  onProblemEdited,
  problem,
}: {
  conversation: ProblemMessage[];
  onConversationChange: (
    problemId: string,
    conversation: ProblemMessage[],
  ) => void;
  onProblemEdited: (problem: Problem) => void;
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

    if (!submittedText || isSubmitting) {
      return;
    }

    const timestamp = new Date().toISOString();
    const optimisticMessage: ProblemMessage = {
      content: submittedText,
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
        content: submittedText,
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
          <ConversationComposer
            autoFocusOnReady
            busy={isSubmitting}
            canSubmit={Boolean(text.trim()) && !isSubmitting}
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
