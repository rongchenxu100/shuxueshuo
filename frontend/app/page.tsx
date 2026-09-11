import { AuthoringWorkspace } from "./_components/authoring-workspace";
import { NavResponseSchema } from "@/lib/contracts";
import { loadFixture } from "@/lib/mock/load-fixture";
import { ProductWorkspace } from "./_components/product-workspace";

export default async function Home() {
  if (process.env.WORKSPACE_MODE !== 'mock') return <ProductWorkspace />;
  const nav = NavResponseSchema.parse(await loadFixture("nav.json"));

  return <AuthoringWorkspace initialNav={nav} />;
}
