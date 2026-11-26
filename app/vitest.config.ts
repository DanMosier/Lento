import { defineConfig } from "vitest/config";

// Unit tests live in test/. The browser tests in e2e/ run with Playwright instead (npm run e2e).
export default defineConfig({ test: { environment: "happy-dom", testTimeout: 60000, include: ["test/**/*.test.ts"] } });
