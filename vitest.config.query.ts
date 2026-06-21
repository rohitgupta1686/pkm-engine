import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/worker-query.spec.ts"],
  },
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler-query.test.toml" },
      miniflare: {
        bindings: {
          PKM_KEY: "test-shared-secret",
          TURSO_URL: "https://test-db.turso.io",
          TURSO_TOKEN: "test-turso-token",
          OPENAI_API_KEY: "test-openai-key",
        },
      },
    }),
  ],
});
