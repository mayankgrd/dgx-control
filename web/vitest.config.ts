import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    // jsdom defaults to about:blank, an OPAQUE origin where localStorage is undefined.
    // A real origin is needed for the storage tests -- and this is exactly the condition
    // api/client.ts guards against in private windows and blocked-storage browsers.
    environmentOptions: { jsdom: { url: "http://localhost:8770" } },
  },
});
