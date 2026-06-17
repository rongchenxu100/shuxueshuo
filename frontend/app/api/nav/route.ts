import { NextResponse } from "next/server";

import { NavResponseSchema } from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";

export async function GET() {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));
  return NextResponse.json(nav);
}
