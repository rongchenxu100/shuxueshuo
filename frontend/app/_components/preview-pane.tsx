import { useState, type ReactNode } from "react";

import {
  previewUrlWithVersion,
  type SelectedWorkspaceObject,
} from "./workspace-model";

export function PreviewPane({
  collapsed,
  onToggleCollapsed,
  selectedObject,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  selectedObject: SelectedWorkspaceObject;
}) {
  const preview = getPreview(selectedObject);
  const [reloadNonce, setReloadNonce] = useState(0);

  if (collapsed) {
    return (
      <section className="flex h-full min-w-0 flex-col items-center border-l border-zinc-200 bg-white">
        <div className="flex h-12 w-full shrink-0 items-center justify-center border-b border-zinc-200">
          <IconButton label="展开右侧预览" onClick={onToggleCollapsed}>
            <ChevronIcon direction="left" />
          </IconButton>
        </div>
      </section>
    );
  }

  return (
    <section className="flex h-full min-w-0 flex-col bg-white">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-2">
        <IconButton label="收起右侧预览" onClick={onToggleCollapsed}>
          <ChevronIcon direction="right" />
        </IconButton>
        <span className="text-sm font-medium text-zinc-700">预览</span>
        <div className="ml-auto flex items-center gap-1">
          <IconButton
            disabled={!preview}
            label="刷新预览"
            onClick={() => setReloadNonce((current) => current + 1)}
          >
            <RefreshIcon />
          </IconButton>
          {preview ? (
            <a
              aria-label="打开预览"
              className="flex size-8 shrink-0 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900"
              href={preview.src}
              rel="noreferrer"
              target="_blank"
              title="打开预览"
            >
              <ExternalLinkIcon />
            </a>
          ) : (
            <IconButton disabled label="打开预览" onClick={() => undefined}>
              <ExternalLinkIcon />
            </IconButton>
          )}
          <IconButton disabled label="添加注释" onClick={() => undefined}>
            <AnnotationIcon />
          </IconButton>
        </div>
      </div>

      <div className="min-h-0 flex-1 bg-zinc-200">
        {preview ? (
          <iframe
            className="h-full w-full border-0 bg-white"
            key={`${preview.src}-${reloadNonce}`}
            src={preview.src}
            title={`${preview.title}预览`}
          />
        ) : (
          <div className="flex h-full items-center justify-center rounded border border-dashed border-zinc-300 bg-zinc-50 text-sm text-zinc-500">
            当前对象暂无网页预览。
          </div>
        )}
      </div>
    </section>
  );
}

function IconButton({
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
      className="flex size-8 shrink-0 items-center justify-center rounded-md text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent disabled:hover:text-zinc-500"
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {children}
    </button>
  );
}

function RefreshIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M20 12a8 8 0 0 1-13.5 5.8M4 12A8 8 0 0 1 17.5 6.2"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
      <path
        d="M17.5 3.8v2.4h-2.4M6.5 20.2v-2.4h2.4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function ExternalLinkIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M14 5h5v5M19 5l-8 8"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M19 14v3.5A1.5 1.5 0 0 1 17.5 19h-11A1.5 1.5 0 0 1 5 17.5v-11A1.5 1.5 0 0 1 6.5 5H10"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function AnnotationIcon() {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d="M6.5 5h11A1.5 1.5 0 0 1 19 6.5v8a1.5 1.5 0 0 1-1.5 1.5H11l-4 3v-3h-.5A1.5 1.5 0 0 1 5 14.5v-8A1.5 1.5 0 0 1 6.5 5Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M8.5 9h7M8.5 12h4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      aria-hidden="true"
      className="size-4"
      fill="none"
      viewBox="0 0 24 24"
    >
      <path
        d={direction === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}

function getPreview(selectedObject: SelectedWorkspaceObject):
  | { src: string; title: string }
  | null {
  if (selectedObject.kind === "problem") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      title: selectedObject.item.shortTitle,
    };
  }

  if (selectedObject.kind === "site_home") {
    return {
      src: selectedObject.item.previewUrl,
      title: selectedObject.item.siteName,
    };
  }

  if (selectedObject.kind === "topic") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      title: selectedObject.item.title,
    };
  }

  return null;
}
