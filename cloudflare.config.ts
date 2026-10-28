import { defineConfig } from "cf/config";

export default defineConfig(({ mode }) => ({
  accountId: "49527944816908496390b8aefdbfba97",
  worker: {
    name: mode === "legacy" ? "website2grav" : "anysite2grav",
    compatibilityDate: "2026-10-28",
    domains: [mode === "legacy" ? "website2grav.djamil.dev" : "anysite2grav.djamil.dev"],
    workersDev: true,
    observability: {
      enabled: true,
      traces: { enabled: true },
    },
  },
}));
