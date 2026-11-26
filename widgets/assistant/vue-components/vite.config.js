import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Builds the components as a UMD library straight into the Python package's
// serve directory; Vue stays external, since trame provides it at runtime.
export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_assistant",
      formats: ["umd"],
      fileName: (format) => `trame_fespp_assistant.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_assistant/module/serve",
    assetsDir: ".",
  },
});
