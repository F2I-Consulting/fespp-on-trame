import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Builds the widget as one UMD library straight into the Python package's
// serve directory; Vue stays external, provided at runtime by the trame
// client as the global `Vue`.
export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_crossplot",
      formats: ["umd"],
      fileName: (format) => `trame_fespp_crossplot.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_crossplot/module/serve",
    assetsDir: ".",
  },
});
