import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// The panel builds as a UMD library into the Python package's serve/
// directory; Vue stays external, provided by trame as the global `Vue`.
export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_volumetrics",
      formats: ["umd"],
      fileName: (format) => `trame_fespp_volumetrics.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_volumetrics/module/serve",
    assetsDir: ".",
  },
});
