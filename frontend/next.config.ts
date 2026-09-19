import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // The local workbench is normally opened at 127.0.0.1:3000. Next's
  // development client otherwise blocks its HMR/runtime requests because
  // 127.0.0.1 and localhost are different origins.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
