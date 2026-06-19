import { useEffect, useRef, useState } from "react";

import type { Problem } from "@/lib/contracts";

import {
  ConversationComposer,
  ImagePreviewDialog,
  SystemFeedback,
  UserPromptMessage,
  usePromptSnapshotRegistry,
} from "./composer";
import type { ProblemConversationAttempt } from "./conversation-types";

export function ProblemConversationPanel({
  conversation,
  onConversationChange,
  problem,
}: {
  conversation: ProblemConversationAttempt[];
  onConversationChange: (
    problemId: string,
    conversation: ProblemConversationAttempt[],
  ) => void;
  problem: Problem;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewImage, setPreviewImage] = useState<{
    alt: string;
    url: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const historyScrollRef = useRef<HTMLDivElement>(null);
  const nextLocalAttemptIdRef = useRef(0);
  const {
    createPromptSnapshot,
    retainConversationPreviews,
  } = usePromptSnapshotRegistry();

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
  }, [conversation]);

  function handleSubmit() {
    if (!text.trim() && !file) {
      return;
    }

    const submittedText = text.trim();
    const submittedFile = file;
    const maxConversationId = conversation.reduce(
      (maxId, attempt) => Math.max(maxId, attempt.id),
      0,
    );
    const nextId = Math.max(nextLocalAttemptIdRef.current, maxConversationId) + 1;
    nextLocalAttemptIdRef.current = nextId;
    const attempt: ProblemConversationAttempt = {
      error: null,
      events: [],
      id: nextId,
      kind: submittedFile ? "upload" : "text",
      prompt: createPromptSnapshot(submittedText, submittedFile),
      status: "completed",
      systemMessage: "已记录到对话，后续将接入题目修改",
    };
    const nextConversation = [...conversation, attempt];

    retainConversationPreviews(nextConversation);
    onConversationChange(problem.id, nextConversation);
    setText("");
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
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
            conversation.map((attempt) => (
              <div className="space-y-5" key={attempt.id}>
                <UserPromptMessage
                  prompt={attempt.prompt}
                  showPreviewImage={setPreviewImage}
                />
                <SystemFeedback attempt={attempt} />
              </div>
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
        </div>
      </div>
      <div className="pointer-events-none shrink-0 bg-gradient-to-t from-zinc-50 via-zinc-50 to-transparent px-4 pb-4 pt-4">
        <div className="pointer-events-auto mx-auto max-w-4xl">
          <ConversationComposer
            canSubmit={Boolean(text.trim() || file)}
            file={file}
            fileInputRef={fileInputRef}
            placeholder="继续输入修改要求"
            setFile={setFile}
            setText={setText}
            showPreviewImage={setPreviewImage}
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
