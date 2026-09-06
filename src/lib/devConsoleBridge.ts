/**
 * 開發時把 webview 裡的 console.log/warn/error 跟未捕捉的例外，一併轉送
 * 到 Python 那一側印出來——這樣在 VS Code 裡用 debugpy 掛 `python main.py`
 * 偵錯時，Debug Console 看到的就不只是 Python 自己的 print/中斷點輸出，
 * 前端在 webview 裡發生的事也會出現在同一個地方，不用另外開瀏覽器
 * DevTools 切來切去對照兩份 log。
 *
 * 只在開發模式（import.meta.env.DEV）啟用：正式打包後的桌面應用程式
 * 通常沒有附著的終端機可以看這些輸出，硬轉送只是白白增加 IPC 呼叫，
 * 沒有實際收益，也不必要地把使用者本機的 console 內容送去 Python 那層。
 */

type ConsoleLevel = "log" | "warn" | "error" | "info" | "debug";

const LEVELS: ConsoleLevel[] = ["log", "warn", "error", "info", "debug"];

function safeStringify(value: unknown): string {
	if (typeof value === "string") return value;
	if (value instanceof Error) {
		return `${value.name}: ${value.message}${value.stack ? `\n${value.stack}` : ""}`;
	}
	try {
		return JSON.stringify(value);
	} catch {
		return String(value);
	}
}

function forward(level: string, args: unknown[]) {
	const message = args.map(safeStringify).join(" ");
	try {
		// pywebview 可能還沒 ready，或這個方法本身呼叫失敗——都不該影響
		// 原本 console 呼叫的正常行為，所以完全吞掉錯誤。
		void window.pywebview?.api?.log_from_frontend?.(level, message);
	} catch {
		/* ignore */
	}
}

/** 呼叫一次即可（main.tsx 進入點呼叫），會覆寫 console.* 方法本身。
 * 用一個旗標避免熱重載（HMR）時重複覆寫、疊加好幾層轉送。
 */
export function installDevConsoleBridge() {
	if (!import.meta.env.DEV) return;
	if (window.__devConsoleBridgeInstalled) return;
	window.__devConsoleBridgeInstalled = true;

	for (const level of LEVELS) {
		const original = console[level].bind(console);
		console[level] = (...args: unknown[]) => {
			original(...args);
			forward(level, args);
		};
	}

	window.addEventListener("error", (event) => {
		forward("error", [
			`Uncaught: ${event.message}`,
			`${event.filename}:${event.lineno}:${event.colno}`,
		]);
	});
	window.addEventListener("unhandledrejection", (event) => {
		forward("error", ["Unhandled promise rejection:", event.reason]);
	});
}
