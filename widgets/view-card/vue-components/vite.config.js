import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_fespp_view_card",
      formats: ["umd"],
      fileName: (format) => `trame_fespp_view_card.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: { globals: { vue: "Vue" } },
    },
    outDir: "../trame_fespp_view_card/module/serve",
    assetsDir: ".",
  },
});
