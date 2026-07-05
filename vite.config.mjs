import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, projectRoot, ""), ...process.env };
  const publicHost = env.MYNAS_PUBLIC_HOST?.trim();
  return {
    root: projectRoot,
    plugins: [vue()],
    server: {
      host: env.MYNAS_HOST || "127.0.0.1",
      allowedHosts: ["localhost", "127.0.0.1", ...(publicHost ? [publicHost] : [])],
      proxy: { "/api": env.MYNAS_API_TARGET || "http://127.0.0.1:8000" },
    },
  };
});
