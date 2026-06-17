import { AuthoringWorkspace } from "./_components/authoring-workspace";
import { NavResponseSchema } from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";

export default async function Home() {
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));

  return <AuthoringWorkspace initialNav={nav} />;
}
