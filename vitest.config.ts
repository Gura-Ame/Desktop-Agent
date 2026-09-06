import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

// 獨立的 vitest 設定檔，而不是把 test 區塊塞進 vite.config.ts——
// production build（vite build）跟測試用的是不同的插件/環境需求
// （測試需要 jsdom、production build 不需要），分開比較乾淨，
// 也不會讓 `npm run build` 意外多帶一份測試設定。
export default mergeConfig(
	viteConfig,
	defineConfig({
		test: {
			environment: "jsdom",
			globals: true,
			setupFiles: ["./src/test/setup.ts"],
			css: false,
		},
	}),
);
