"use client";

import { useState } from "react";

import { TutorChat } from "@/app/_components/tutor-chat";

export function MockPublicPage({
  description,
  path,
  problemId,
  title,
}: {
  description: string;
  path: string;
  problemId?: string;
  title: string;
}) {
  const [isTutorOpen, setIsTutorOpen] = useState(false);

  return (
    <main className="min-h-full bg-zinc-50 text-zinc-950">
      <section className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-6 py-20">
        <p className="mb-3 text-sm font-medium text-teal-700">Phase 5 mock</p>
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-4 text-base leading-7 text-zinc-600">
          {description}
        </p>
        <p className="mt-8 rounded-md border border-zinc-200 bg-white px-4 py-3 font-mono text-sm text-zinc-600">
          {path}
        </p>
        {problemId ? (
          <button
            className="mt-6 w-fit rounded-md border border-teal-200 bg-teal-50 px-4 py-2 text-sm font-medium text-teal-700 transition hover:bg-teal-100"
            onClick={() => setIsTutorOpen(true)}
            type="button"
          >
            问这道题
          </button>
        ) : null}
      </section>
      {problemId && isTutorOpen ? (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-zinc-950/20"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setIsTutorOpen(false);
            }
          }}
          role="presentation"
        >
          <aside
            aria-label="题目学习对话"
            className="flex h-full w-full max-w-xl flex-col border-l border-zinc-200 bg-zinc-50 shadow-2xl"
          >
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-200 bg-white px-4">
              <h2 className="text-sm font-medium text-zinc-800">问这道题</h2>
              <button
                className="rounded-md px-2 py-1 text-sm text-zinc-500 transition hover:bg-zinc-100"
                onClick={() => setIsTutorOpen(false)}
                type="button"
              >
                关闭
              </button>
            </div>
            <TutorChat
              problemId={problemId}
              problemTitle={title}
            />
          </aside>
        </div>
      ) : null}
    </main>
  );
}
