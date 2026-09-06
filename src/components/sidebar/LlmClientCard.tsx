import { Cpu, FolderOpen, History, Loader2, RefreshCw } from "lucide-react";
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
	recentModels?: string[];
	onPickModelFile?: () => void;
	isModelLoading?: boolean;
	loadMessage?: { type: "success" | "error" | "info"; text: string } | null;
	onClearRecentModels?: () => void;
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
	recentModels = [],
	onPickModelFile,
	isModelLoading = false,
	loadMessage,
	onClearRecentModels,
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
					disabled={isModelLoading}
					className="hover:text-zinc-200 transition-colors disabled:opacity-40"
					title="重置與檢查連線"
				>
					<RefreshCw size={12} className={isModelLoading ? "animate-spin" : ""} />
				</button>
			</div>

			{/* 模式切換 */}
			<div className="grid grid-cols-2 gap-1">
				{CLIENT_MODES.map((m) => (
					<button
						key={m.value}
						onClick={() => setClientMode(m.value)}
						disabled={isModelLoading}
						title={m.hint}
						className={`flex flex-col items-center gap-1 py-2 px-1 rounded-lg text-[10px] font-medium border transition-all active:scale-[0.97] ${
							clientMode === m.value
								? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
								: "bg-zinc-950 border-zinc-800 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
						} ${isModelLoading ? "opacity-50 cursor-not-allowed" : ""}`}
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

			{/* Local GGUF：顯示模型路徑與歷史紀錄 */}
			{clientMode === "local_llama" && (
				<div className="space-y-2.5">
					{/* 歷史載入模型清單 */}
					{recentModels.length > 0 && (
						<div className="space-y-1">
							<div className="flex items-center justify-between">
								<span className="flex items-center gap-1 text-[10px] text-zinc-400">
									<History size={11} /> 歷史模型記錄 ({recentModels.length})
								</span>
								{onClearRecentModels && (
									<button
										type="button"
										onClick={onClearRecentModels}
										disabled={isModelLoading}
										className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-40"
										title="清除歷史紀錄"
									>
										清除
									</button>
								)}
							</div>
							<select
								value={recentModels.includes(modelPath) ? modelPath : ""}
								onChange={(e) => {
									if (e.target.value) {
										setModelPath(e.target.value);
									}
								}}
								disabled={isModelLoading}
								className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2 py-1.5 text-[11px] text-zinc-300 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono truncate disabled:opacity-50"
							>
								<option value="">選擇歷史模型記錄...</option>
								{recentModels.map((p) => {
									const fileName = p.split(/[\\/]/).pop() || p;
									return (
										<option key={p} value={p} title={p}>
											{fileName}
										</option>
									);
								})}
							</select>
						</div>
					)}

					{/* 模型路徑輸入與瀏覽按鈕 */}
					<div className="space-y-1">
						<div className="flex items-center justify-between">
							<label className="text-[11px] text-zinc-400">GGUF 模型檔案路徑</label>
							{onPickModelFile && (
								<button
									type="button"
									onClick={onPickModelFile}
									disabled={isModelLoading}
									className="flex items-center gap-1 text-[10px] text-emerald-400 hover:text-emerald-300 transition-colors disabled:opacity-50"
									title="開啟檔案對話框選取 .gguf 檔案"
								>
									<FolderOpen size={11} />
									<span>瀏覽檔案</span>
								</button>
							)}
						</div>
						<div className="relative flex items-center">
							<input
								type="text"
								value={modelPath}
								onChange={(e) => setModelPath(e.target.value)}
								disabled={isModelLoading}
								placeholder="C:\path\to\model.gguf"
								className="w-full bg-zinc-950 border border-zinc-800 rounded-lg pl-2.5 pr-8 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono placeholder:text-zinc-600 disabled:opacity-50"
							/>
							{onPickModelFile && (
								<button
									type="button"
									onClick={onPickModelFile}
									disabled={isModelLoading}
									className="absolute right-2 text-zinc-500 hover:text-zinc-300 disabled:opacity-40 transition-colors"
									title="瀏覽本機檔案"
								>
									<FolderOpen size={14} />
								</button>
							)}
						</div>
					</div>
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

			{/* 載入中動態進度條與使用者提示 */}
			{clientMode === "local_llama" && isModelLoading && (
				<div className="bg-zinc-950/80 border border-emerald-500/30 rounded-lg p-2.5 space-y-2">
					<div className="flex items-center justify-between text-[11px]">
						<span className="flex items-center gap-1.5 text-emerald-400 font-medium">
							<Loader2 size={13} className="animate-spin" />
							載入模型中...
						</span>
						<span className="text-[10px] text-zinc-500">配置顯存與權重</span>
					</div>
					{/* 進度條脈衝動畫 */}
					<div className="h-1.5 w-full bg-zinc-800 rounded-full overflow-hidden">
						<div className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-emerald-500 rounded-full animate-pulse w-full" />
					</div>
					<p className="text-[10px] text-zinc-400 leading-tight">
						模型權重載入可能需要數秒至數十秒，完成後將自動轉為綠燈。
					</p>
				</div>
			)}

			{/* 提示或錯誤訊息 */}
			{loadMessage && (
				<div
					className={`text-[11px] px-2.5 py-1.5 rounded-lg border leading-tight ${
						loadMessage.type === "success"
							? "bg-emerald-950/40 border-emerald-500/30 text-emerald-300"
							: loadMessage.type === "error"
								? "bg-rose-950/40 border-rose-500/30 text-rose-300"
								: "bg-zinc-800/60 border-zinc-700 text-zinc-300"
					}`}
				>
					{loadMessage.text}
				</div>
			)}

			<button
				onClick={applyApiConfig}
				disabled={isModelLoading}
				className={`w-full font-medium py-1.5 rounded-lg text-xs shadow transition-all active:scale-[0.98] flex items-center justify-center gap-1.5 ${
					isModelLoading
						? "bg-zinc-800 text-zinc-400 cursor-not-allowed"
						: "bg-zinc-100 hover:bg-white text-zinc-950"
				}`}
			>
				{isModelLoading && <Loader2 size={13} className="animate-spin" />}
				{isModelLoading
					? "模型載入中..."
					: clientMode === "local_llama"
						? "載入模型"
						: "套用連線設定"}
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
