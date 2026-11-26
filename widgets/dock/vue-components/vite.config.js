import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_dock",
      formats: ["umd"],
      fileName: (format) => `trame_fespp_dock.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_dock/module/serve",
    assetsDir: ".",
  },
});
