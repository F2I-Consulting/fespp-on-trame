import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    lib: {
      entry: "./src/main.js",
      name: "trame_welllog",
      formats: ["umd"],
      // Force a .js extension: with "type":"module" in package.json vite would
      // otherwise emit the UMD bundle as .umd.cjs, breaking the module's script path.
      fileName: (format) => `trame_welllog.${format}.js`,
    },
    rollupOptions: {
      external: ["vue"],
      output: {
        globals: {
          vue: "Vue",
        },
      },
    },
    outDir: "../trame_welllog/module/serve",
    assetsDir: ".",
  },
});
