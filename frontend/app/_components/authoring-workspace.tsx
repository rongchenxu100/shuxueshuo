"use client";

import { useMemo, useState } from "react";

import type { NavResponse } from "@/lib/contracts";

import { MainPane } from "./main-pane";
import { PreviewPane } from "./preview-pane";
import { Sidebar } from "./sidebar";
import {
  getInitialSelection,
  resolveSelection,
  type AutosaveState,
  type SelectedWorkspaceObject,
  type WorkspaceSelection,
} from "./workspace-model";

export function AuthoringWorkspace({ initialNav }: { initialNav: NavResponse }) {
  const [selection, setSelection] = useState<WorkspaceSelection>(() =>
    getInitialSelection(initialNav),
  );
  const [autosaveState] = useState<AutosaveState>("saved");

  const selectedObject = useMemo<SelectedWorkspaceObject>(
    () => resolveSelection(initialNav, selection),
    [initialNav, selection],
  );

  return (
    <main className="h-full overflow-x-auto bg-zinc-100 text-zinc-950">
      <div className="grid h-full min-w-[1060px] grid-cols-[280px_minmax(360px,1fr)_minmax(420px,46vw)]">
        <Sidebar
          nav={initialNav}
          selection={selection}
          onSelect={setSelection}
        />
        <MainPane
          autosaveState={autosaveState}
          selectedObject={selectedObject}
        />
        <PreviewPane selectedObject={selectedObject} />
      </div>
    </main>
  );
}
