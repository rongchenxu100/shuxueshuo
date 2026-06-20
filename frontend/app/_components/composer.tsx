import {
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";

import type { ProblemMessage, UploadJobProgressEvent } from "@/lib/contracts";

import type {
  NewProblemPromptSnapshot,
  ProblemConversationAttempt,
  ProblemCreationScenario,
} from "./conversation-types";

type PreviewImage = { alt: string; url: string };

export function usePromptSnapshotRegistry() {
  const promptPreviewUrlsRef = useRef<string[]>([]);
  const retainedPromptPreviewUrlsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const promptPreviewUrls = promptPreviewUrlsRef.current;
    const retainedPromptPreviewUrls = retainedPromptPreviewUrlsRef.current;

    return () => {
      promptPreviewUrls.forEach((previewUrl) => {
        if (!retainedPromptPreviewUrls.has(previewUrl)) {
          URL.revokeObjectURL(previewUrl);
        }
      });
    };
  }, []);

  function createPromptSnapshot(
    submittedText: string,
    submittedFile: File | null,
  ): NewProblemPromptSnapshot {
    let filePreviewUrl: string | null = null;

    if (submittedFile?.type.startsWith("image/")) {
      filePreviewUrl = URL.createObjectURL(submittedFile);
      promptPreviewUrlsRef.current.push(filePreviewUrl);
    }

    return {
      fileName: submittedFile?.name ?? null,
      filePreviewUrl,
      text: submittedText,
    };
  }

  function retainConversationPreviews(
    conversation: ProblemConversationAttempt[],
  ) {
    conversation.forEach((attempt) => {
      if (attempt.prompt.filePreviewUrl) {
        retainedPromptPreviewUrlsRef.current.add(attempt.prompt.filePreviewUrl);
      }
    });
  }

  return {
    createPromptSnapshot,
    retainConversationPreviews,
  };
}

export function ConversationComposer({
  autoFocusOnReady = false,
  busy = false,
  canSubmit,
  disabled = false,
  file,
  fileInputRef,
  onSubmit,
  placeholder,
  scenario,
  setFile,
  setScenario,
  setText,
  showAttachmentButton = true,
  showPreviewImage,
  showScenarioSelect = false,
  submitLabel = "发送消息",
  text,
}: {
  autoFocusOnReady?: boolean;
  busy?: boolean;
  canSubmit: boolean;
  disabled?: boolean;
  file: File | null;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onSubmit: () => void;
  placeholder: string;
  scenario?: ProblemCreationScenario;
  setFile: (file: File | null) => void;
  setScenario?: (scenario: ProblemCreationScenario) => void;
  setText: (text: string) => void;
  showAttachmentButton?: boolean;
  showPreviewImage: (image: PreviewImage) => void;
  showScenarioSelect?: boolean;
  submitLabel?: string;
  text: string;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const wasDisabledRef = useRef(disabled || busy);
  const filePreviewUrl = useMemo(() => {
    if (!file || !file.type.startsWith("image/")) {
      return null;
    }

    return URL.createObjectURL(file);
  }, [file]);

  useEffect(() => {
    return () => {
      if (filePreviewUrl) {
        URL.revokeObjectURL(filePreviewUrl);
      }
    };
  }, [filePreviewUrl]);

  function clearFile() {
    setFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  const isDisabled = disabled || busy;
  const canShowScenarioSelect =
    showScenarioSelect && scenario !== undefined && setScenario;

  useEffect(() => {
    if (autoFocusOnReady && wasDisabledRef.current && !isDisabled) {
      textareaRef.current?.focus();
    }

    wasDisabledRef.current = isDisabled;
  }, [autoFocusOnReady, isDisabled]);

  return (
    <section className="rounded-[22px] border border-zinc-200 bg-white px-4 py-2.5 shadow-sm transition focus-within:border-zinc-300 focus-within:shadow-md">
      <input
        accept="image/*"
        className="sr-only"
        disabled={isDisabled}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        ref={fileInputRef}
        type="file"
      />
      {filePreviewUrl ? (
        <div className="relative mb-3 size-24 overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-100">
          <button
            aria-label="查看图片"
            className="block h-full w-full"
            onClick={() =>
              showPreviewImage({
                alt: file?.name ?? "已附加图片",
                url: filePreviewUrl,
              })
            }
            type="button"
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- Blob previews cannot be optimized by next/image. */}
            <img
              alt={file?.name ?? "已附加图片"}
              className="h-full w-full object-cover"
              src={filePreviewUrl}
            />
          </button>
          <button
            aria-label="移除图片"
            className="absolute right-2 top-2 flex size-7 items-center justify-center rounded-full bg-zinc-900 text-white shadow-sm transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-400"
            disabled={isDisabled}
            onClick={clearFile}
            type="button"
          >
            <XIcon />
          </button>
        </div>
      ) : null}
      <textarea
        className="min-h-20 w-full resize-none bg-transparent px-1 py-2 text-sm leading-6 outline-none placeholder:text-zinc-400"
        disabled={isDisabled}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            if (canSubmit) {
              onSubmit();
            }
          }
        }}
        onChange={(event) => setText(event.target.value)}
        placeholder={placeholder}
        ref={textareaRef}
        value={text}
      />
      {file && !filePreviewUrl ? (
        <div className="mb-2 flex items-center gap-2 rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-600">
          <span className="truncate">已附加：{file.name}</span>
          <button
            className="rounded px-1 text-zinc-400 hover:text-zinc-800"
            disabled={isDisabled}
            onClick={clearFile}
            type="button"
          >
            移除
          </button>
        </div>
      ) : null}
      <div className="flex items-center gap-2">
        {showAttachmentButton ? (
          <ComposerIconButton
            disabled={isDisabled}
            label="附加图片"
            onClick={() => fileInputRef.current?.click()}
          >
            <PlusIcon />
          </ComposerIconButton>
        ) : null}
        {canShowScenarioSelect ? (
          <select
            aria-label="mock 场景"
            className="ml-auto rounded-md bg-transparent px-2 py-1.5 text-sm text-zinc-500 outline-none transition hover:bg-zinc-100 hover:text-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={isDisabled}
            onChange={(event) =>
              setScenario(event.target.value as ProblemCreationScenario)
            }
            value={scenario}
          >
            <option value="success">成功</option>
            <option value="rejected">非题目图片</option>
            <option value="failed">生成失败</option>
            <option value="disconnect">SSE 中断</option>
          </select>
        ) : null}
        <button
          aria-label={submitLabel}
          className={`flex size-9 items-center justify-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300 ${
            canShowScenarioSelect ? "" : "ml-auto"
          }`}
          disabled={!canSubmit}
          onClick={onSubmit}
          title={submitLabel}
          type="button"
        >
          {busy ? <span className="text-xs">...</span> : <ArrowUpIcon />}
        </button>
      </div>
    </section>
  );
}

export function UserPromptMessage({
  prompt,
  showPreviewImage,
}: {
  prompt: NewProblemPromptSnapshot;
  showPreviewImage: (image: PreviewImage) => void;
}) {
  return (
    <div className="flex justify-end">
      <div className="flex max-w-[82%] flex-col items-end gap-2">
        {prompt.filePreviewUrl ? (
          <button
            aria-label="查看图片"
            className="overflow-hidden rounded-xl border border-zinc-200 bg-zinc-100"
            onClick={() =>
              showPreviewImage({
                alt: prompt.fileName ?? "题目图片",
                url: prompt.filePreviewUrl ?? "",
              })
            }
            type="button"
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- Blob previews cannot be optimized by next/image. */}
            <img
              alt={prompt.fileName ?? "题目图片"}
              className="size-24 object-cover"
              src={prompt.filePreviewUrl}
            />
          </button>
        ) : null}
        <div className="rounded-2xl bg-zinc-200 px-4 py-3 text-sm leading-6 text-zinc-900">
          {prompt.text ? (
            <p className="whitespace-pre-wrap">{prompt.text}</p>
          ) : (
            <p>上传题目图片</p>
          )}
          {prompt.fileName && !prompt.filePreviewUrl ? (
            <p className="mt-2 rounded-md bg-white/70 px-2 py-1 text-xs text-zinc-600">
              附件：{prompt.fileName}
            </p>
          ) : null}
          {prompt.fileName && prompt.filePreviewUrl ? (
            <p className="mt-1 text-xs text-zinc-500">{prompt.fileName}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function ProblemMessageItem({
  message,
  showPreviewImage,
}: {
  message: ProblemMessage;
  showPreviewImage: (image: PreviewImage) => void;
}) {
  if (message.role === "user") {
    const imageAttachment = message.attachments?.find((attachment) =>
      attachment.mimeType?.startsWith("image/"),
    );

    return (
      <div className="flex justify-end">
        <div className="flex max-w-[82%] flex-col items-end gap-2">
          {imageAttachment ? (
            <button
              aria-label="查看图片"
              className="overflow-hidden rounded-xl border border-zinc-200 bg-zinc-100"
              onClick={() =>
                showPreviewImage({
                  alt: imageAttachment.filename ?? "题目图片",
                  url: imageAttachment.url,
                })
              }
              type="button"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- Fixture and upload previews are not optimized assets. */}
              <img
                alt={imageAttachment.filename ?? "题目图片"}
                className="size-24 object-cover"
                src={imageAttachment.url}
              />
            </button>
          ) : null}
          <div className="rounded-2xl bg-zinc-200 px-4 py-3 text-sm leading-6 text-zinc-900">
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.attachments?.length && !imageAttachment ? (
              <p className="mt-2 rounded-md bg-white/70 px-2 py-1 text-xs text-zinc-600">
                附件：{message.attachments.length} 个
              </p>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[82%] space-y-2">
      <div className="text-sm font-medium text-zinc-500">
        {message.role === "assistant" ? "已处理" : "系统消息"}
      </div>
      <div className="whitespace-pre-wrap text-sm leading-6 text-zinc-800">
        {message.content}
      </div>
    </div>
  );
}

export function ImagePreviewDialog({
  alt,
  onClose,
  src,
}: {
  alt: string;
  onClose: () => void;
  src: string;
}) {
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseRef.current();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-8 py-8"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="relative max-h-full max-w-4xl rounded-xl bg-white p-3 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          aria-label="关闭图片预览"
          className="absolute right-2 top-2 flex size-8 items-center justify-center rounded-full bg-zinc-900 text-white transition hover:bg-zinc-700"
          onClick={onClose}
          type="button"
        >
          <XIcon />
        </button>
        {/* eslint-disable-next-line @next/next/no-img-element -- Blob previews cannot be optimized by next/image. */}
        <img
          alt={alt}
          className="max-h-[80vh] max-w-full rounded-lg object-contain"
          src={src}
        />
        <p className="mt-2 max-w-[80vw] truncate px-1 text-xs text-zinc-500">
          {alt}
        </p>
      </div>
    </div>
  );
}

export function SystemFeedback({
  attempt,
}: {
  attempt: ProblemConversationAttempt;
}) {
  const isFailed = attempt.status === "failed";
  const statusText = isFailed
    ? "处理失败"
    : attempt.status === "completed"
      ? (attempt.systemMessage ?? "已完成")
      : attempt.kind === "text"
        ? "正在创建草稿题目..."
        : "正在处理上传...";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-500">
        <span
          className={`size-2 rounded-full ${
            isFailed ? "bg-red-500" : "bg-teal-500"
          }`}
        />
        <span>{statusText}</span>
      </div>
      {attempt.events.length ? (
        <ol className="space-y-2">
          {attempt.events.map((event, index) => (
            <li
              className="flex gap-2 text-sm leading-6 text-zinc-700"
              key={`${event.type}-${index}`}
            >
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-zinc-400" />
              <span>{uploadEventLabel(event)}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {attempt.error ? (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {attempt.error}
        </p>
      ) : null}
    </div>
  );
}

export function uploadEventLabel(event: UploadJobProgressEvent): string {
  if (event.type === "progress") {
    return event.message;
  }

  if (event.type === "done") {
    return "完成";
  }

  if (event.type === "rejected") {
    return event.message;
  }

  return event.error.message;
}

function ComposerIconButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className="flex size-8 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function PlusIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-5"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M12 5v14M5 12h14"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function XIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="m7 7 10 10M17 7 7 17"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2"
      />
    </svg>
  );
}

function ArrowUpIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-5"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M12 19V5m0 0-6 6m6-6 6 6"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}
