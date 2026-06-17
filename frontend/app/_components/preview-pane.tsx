import type { PublishStatus } from "@/lib/contracts";

import {
  previewUrlWithVersion,
  publishStatusLabel,
  type SelectedWorkspaceObject,
} from "./workspace-model";

export function PreviewPane({
  selectedObject,
}: {
  selectedObject: SelectedWorkspaceObject;
}) {
  const preview = getPreview(selectedObject);

  return (
    <section className="flex h-full flex-col bg-white">
      <div className="border-b border-zinc-200 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-medium text-zinc-500">右侧预览</p>
            <h2 className="mt-1 truncate text-lg font-semibold">
              {preview?.title ?? "暂无预览"}
            </h2>
          </div>
        </div>
        {preview?.status ? (
          <p className="mt-2 text-xs text-zinc-500">
            {publishStatusLabel(preview.status)}
          </p>
        ) : null}
      </div>

      <div className="flex-1 bg-zinc-200 p-3">
        {preview ? (
          <iframe
            className="h-full w-full rounded border border-zinc-300 bg-white"
            key={preview.src}
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

function getPreview(selectedObject: SelectedWorkspaceObject):
  | { src: string; status: PublishStatus; title: string }
  | null {
  if (selectedObject.kind === "problem") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      status: selectedObject.item.status,
      title: selectedObject.item.shortTitle,
    };
  }

  if (selectedObject.kind === "site_home") {
    return {
      src: selectedObject.item.previewUrl,
      status: selectedObject.item.status,
      title: selectedObject.item.siteName,
    };
  }

  if (selectedObject.kind === "topic") {
    return {
      src: previewUrlWithVersion(
        selectedObject.item.previewUrl,
        selectedObject.item.previewVersion,
      ),
      status: selectedObject.item.status,
      title: selectedObject.item.title,
    };
  }

  return null;
}
