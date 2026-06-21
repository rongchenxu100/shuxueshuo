import { NextResponse } from "next/server";

import {
  NavResponseSchema,
  PatchSiteHomeRequestSchema,
  PatchSiteHomeResponseSchema,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { patchMockSiteHome } from "@/lib/mock/topic-management";

export async function PATCH(request: Request) {
  const payload = PatchSiteHomeRequestSchema.parse(await request.json());
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const siteHome = patchMockSiteHome(nav.siteHome, payload);

  return NextResponse.json(PatchSiteHomeResponseSchema.parse({ siteHome }));
}
