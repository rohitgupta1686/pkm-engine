import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Scope to clip worker tests only; query worker has its own vitest.config.query.ts.
    include: ["test/worker-clip.spec.ts"],
  },
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.toml" },
      miniflare: {
        bindings: { PKM_KEY: "test-shared-secret", GH_PAT: "test-pat" },
      },
    }),
  ],
});