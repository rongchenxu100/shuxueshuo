import { NextResponse } from "next/server";

import {
  NavResponseSchema,
  PublishSiteHomeResponseSchema,
} from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { publishMockSiteHome } from "@/lib/mock/publish";

export async function POST() {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  const siteHome = publishMockSiteHome(nav.siteHome);

  return NextResponse.json(
    PublishSiteHomeResponseSchema.parse({
      publicUrl: siteHome.publicUrl,
      siteHome,
    }),
  );
}
