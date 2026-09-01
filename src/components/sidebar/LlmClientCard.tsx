import { Cpu, RefreshCw } from "lucide-react";
import type { ClientMode, ServerStatus } from "../../types";
import { CLIENT_MODES } from "./constants";

type LlmClientCardProps = {
	clientMode: ClientMode;
	setClientMode: (mode: ClientMode) => void;
	baseUrl: string;
	setBaseUrl: (url: string) => void;
	apiKey: string;
	setApiKey: (key: string) => void;
	modelName: string;
	setModelName: (name: string) => void;
	modelPath: string;
	setModelPath: (path: string) => void;
	applyApiConfig: () => void;
	serverStatus: ServerStatus;
	checkServerHealth: () => void;
};

export default function LlmClientCard({
	clientMode,
	setClientMode,
	baseUrl,
	setBaseUrl,
	apiKey,
	setApiKey,
	modelName,
	setModelName,
	modelPath,
	setModelPath,
	applyApiConfig,
	serverStatus,
	checkServerHealth,
}: LlmClientCardProps) {
	const activeClientMode = CLIENT_MODES.find((m) => m.value === clientMode);

	return (
		<div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-3 shadow-sm">
			<div className="flex items-center justify-between text-xs font-medium text-zinc-400">
				<span className="flex items-center gap-1.5">
					<Cpu size={14} /> LLM 客戶端配置
				</span>
				<button
					onClick={checkServerHealth}
					className="hover:text-zinc-200 transition-colors"
					title="重置與檢查連線"
				>
					<RefreshCw size={12} />
				</button>
			</div>

			{/* 模式切換 */}
			<div className="grid grid-cols-2 gap-1">
				{CLIENT_MODES.map((m) => (
					<button
						key={m.value}
						onClick={() => setClientMode(m.value)}
						title={m.hint}
						className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium border transition-all active:scale-[0.97] ${
							clientMode === m.value
								? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
								: "bg-zinc-950 border-zinc-800 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
						}`}
					>
						{m.icon}
						{m.label}
					</button>
				))}
			</div>

			{/* 模式說明 */}
			<p className="text-[10px] text-zinc-500 leading-relaxed">
				{activeClientMode?.hint}
			</p>

			{/* Local GGUF：顯示模型路徑 */}
			{clientMode === "local_llama" && (
				<div className="space-y-1">
					<label className="text-[11px] text-zinc-400">GGUF 模型路徑</label>
					<input
						type="text"
						value={modelPath}
						onChange={(e) => setModelPath(e.target.value)}
						placeholder="C:\path\to\model.gguf"
						className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono placeholder:text-zinc-600"
					/>
				</div>
			)}

			{/* Remote API：顯示 Base URL、API Key、Model Name */}
			{clientMode === "remote_api" && (
				<div className="space-y-2">
					<div className="space-y-1">
						<label className="text-[11px] text-zinc-400">API Base URL</label>
						<input
							type="text"
							value={baseUrl}
							onChange={(e) => setBaseUrl(e.target.value)}
							className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono"
						/>
					</div>

					<div className="space-y-1">
						<label className="text-[11px] text-zinc-400">API Key</label>
						<input
							type="password"
							value={apiKey}
							onChange={(e) => setApiKey(e.target.value)}
							placeholder="sk-..."
							className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono placeholder:text-zinc-600"
						/>
					</div>

					<div className="space-y-1">
						<label className="text-[11px] text-zinc-400">Model Name</label>
						<input
							type="text"
							value={modelName}
							onChange={(e) => setModelName(e.target.value)}
							className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono"
						/>
					</div>
				</div>
			)}

			<button
				onClick={applyApiConfig}
				className="w-full bg-zinc-100 hover:bg-white text-zinc-950 font-medium py-1.5 rounded-lg text-xs shadow transition-all active:scale-[0.98]"
			>
				{clientMode === "local_llama" ? "載入模型" : "套用連線設定"}
			</button>

			<div className="flex items-center justify-between text-xs pt-2 border-t border-zinc-800/80">
				<span className="text-zinc-400">狀態</span>
				<span className="flex items-center gap-1.5 font-medium">
					<span
						className={`w-2 h-2 rounded-full ${serverStatus.running ? "bg-emerald-500 animate-pulse" : "bg-rose-500"}`}
					/>
					<span
						className={serverStatus.running ? "text-zinc-200" : "text-zinc-400"}
					>
						{serverStatus.msg}
					</span>
				</span>
			</div>
		</div>
	);
}
