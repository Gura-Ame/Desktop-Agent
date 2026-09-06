import { FolderOpen, Globe } from "lucide-react";
import type { ClientMode, ExecutionMode, PermissionMode } from "../../types";

export const MODE_OPTIONS: {
	value: ExecutionMode;
	label: string;
	hint: string;
}[] = [
	{
		value: "STEP_BY_STEP",
		label: "逐步確認",
		hint: "無視任務自己的判斷，每完成一步就暫停，等待你確認才繼續",
	},
	{
		value: "SMART",
		label: "智慧確認",
		hint: "由模型規劃時標的「需要確認」決定：高風險步驟才暫停，其餘自動繼續",
	},
	{
		value: "AUTO",
		label: "全自動",
		hint: "無視任務自己的判斷，中間不再暫停，直到全部完成或需要你介入",
	},
];

export const PERMISSION_MODE_OPTIONS: {
	value: PermissionMode;
	label: string;
	hint: string;
}[] = [
	{
		value: "ask",
		label: "一律詢問",
		hint: "任何有副作用（記憶寫入、網頁互動）或高風險（滑鼠鍵盤、執行程式碼）的工具，第一次使用都要你同意",
	},
	{
		value: "ask_dangerous_only",
		label: "只問高風險",
		hint: "記憶寫入、網頁互動這類中風險工具自動放行，滑鼠鍵盤、執行程式碼這類高風險工具還是會問",
	},
	{
		value: "auto",
		label: "全部信任",
		hint: "完全不詢問，所有工具都直接執行——只建議進階使用者在完全信任目前設定的模型時使用",
	},
];

export const CLIENT_MODES: {
	value: ClientMode;
	label: string;
	icon: React.ReactNode;
	hint: string;
}[] = [
	{
		value: "local_llama",
		label: "Local GGUF",
		icon: <FolderOpen size={13} />,
		hint: "直接用 llama-cpp-python 載入 GGUF 模型，無需啟動 HTTP 伺服器",
	},
	{
		value: "remote_api",
		label: "Remote API",
		icon: <Globe size={13} />,
		hint: "連接任意 OpenAI 相容 API（LM Studio、OpenAI、本地 vLLM 等）",
	},
];
