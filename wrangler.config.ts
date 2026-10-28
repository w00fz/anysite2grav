import { defineWranglerConfig } from "wrangler/experimental-config";

export default defineWranglerConfig(({ mode }) => ({
  assetsDirectory: mode === "legacy" ? "hosting/legacy" : "docs",
}));
