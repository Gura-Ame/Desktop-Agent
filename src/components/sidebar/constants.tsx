import { FolderOpen, Globe } from "lucide-react";
import type { ClientMode, ExecutionMode } from "../../types";

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
