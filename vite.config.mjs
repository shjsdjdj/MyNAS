import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, projectRoot, ""), ...process.env };
  const publicHost = env.MYNAS_PUBLIC_HOST?.trim();
  return {
    root: projectRoot,
    plugins: [
      vue(),
      VitePWA({
        registerType: "prompt",
        injectRegister: "script-defer",
        manifestFilename: "manifest.webmanifest",
        includeAssets: [
          "pwa-icon.svg",
          "pwa-192x192.png",
          "pwa-512x512.png",
          "apple-touch-icon.png",
        ],
        manifest: {
          name: "MyNAS 管理中心",
          short_name: "MyNAS",
          description: "免费开源的个人云，用于管理照片、文件、多盘与备份。",
          lang: "zh-CN",
          theme_color: "#4b68f4",
          background_color: "#f4f6fb",
          display: "standalone",
          scope: "/",
          start_url: "/",
          prefer_related_applications: false,
          icons: [
            {
              src: "/pwa-192x192.png",
              sizes: "192x192",
              type: "image/png",
              purpose: "any maskable",
            },
            {
              src: "/pwa-512x512.png",
              sizes: "512x512",
              type: "image/png",
              purpose: "any maskable",
            },
          ],
        },
        workbox: {
          globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2,webmanifest}"],
          navigateFallback: "/index.html",
          navigateFallbackDenylist: [/^\/api\//],
          cleanupOutdatedCaches: true,
        },
        devOptions: { enabled: false },
      }),
    ],
    server: {
      host: env.MYNAS_HOST || "127.0.0.1",
      allowedHosts: ["localhost", "127.0.0.1", ...(publicHost ? [publicHost] : [])],
      proxy: { "/api": env.MYNAS_API_TARGET || "http://127.0.0.1:8000" },
    },
  };
});
