import {
	Check,
	ChevronDown,
	Cpu,
	FolderOpen,
	History,
	Loader2,
	RefreshCw,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
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

function fileNameOf(path: string) {
	return path.split(/[\\/]/).pop() || path;
}

/** 自訂歷史模型選單：截斷長檔名，避免原生 select 把 sidebar 撐出橫向捲軸 */
function RecentModelPicker({
	recentModels,
	modelPath,
	setModelPath,
	disabled,
	onClear,
}: {
	recentModels: string[];
	modelPath: string;
	setModelPath: (path: string) => void;
	disabled?: boolean;
	onClear?: () => void;
}) {
	const [open, setOpen] = useState(false);
	const [menuPos, setMenuPos] = useState<{
		top: number;
		left: number;
		width: number;
	} | null>(null);
	const rootRef = useRef<HTMLDivElement>(null);
	const btnRef = useRef<HTMLButtonElement>(null);
	const selected = recentModels.includes(modelPath) ? modelPath : "";

	const updatePos = () => {
		const el = btnRef.current;
		if (!el) return;
		const r = el.getBoundingClientRect();
		setMenuPos({ top: r.bottom + 4, left: r.left, width: r.width });
	};

	useEffect(() => {
		if (!open) return;
		updatePos();
		const onDoc = (e: MouseEvent) => {
			if (!rootRef.current?.contains(e.target as Node)) {
				const menu = document.getElementById("recent-model-menu");
				if (menu?.contains(e.target as Node)) return;
				setOpen(false);
			}
		};
		const onScroll = () => updatePos();
		document.addEventListener("mousedown", onDoc);
		window.addEventListener("resize", onScroll);
		window.addEventListener("scroll", onScroll, true);
		return () => {
			document.removeEventListener("mousedown", onDoc);
			window.removeEventListener("resize", onScroll);
			window.removeEventListener("scroll", onScroll, true);
		};
	}, [open]);

	return (
		<div className="space-y-1 min-w-0" ref={rootRef}>
			<div className="flex items-center justify-between gap-2 min-w-0">
				<span className="flex items-center gap-1 text-[10px] text-zinc-500 dark:text-zinc-400 truncate">
					<History size={11} className="shrink-0" /> 歷史模型 ({recentModels.length})
				</span>
				{onClear && (
					<button
						type="button"
						onClick={onClear}
						disabled={disabled}
						className="shrink-0 text-[10px] text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-300 transition-colors disabled:opacity-40"
						title="清除歷史紀錄"
					>
						清除
					</button>
				)}
			</div>

			<div className="relative min-w-0">
				<button
					ref={btnRef}
					type="button"
					disabled={disabled}
					onClick={() => setOpen((v) => !v)}
					title={selected || "選擇歷史模型記錄"}
					className="w-full min-w-0 flex items-center gap-1.5 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-xl px-2.5 py-1.5 text-xs text-left text-zinc-800 dark:text-zinc-200 hover:border-zinc-300 dark:hover:border-zinc-700 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all disabled:opacity-50 shadow-sm"
				>
					<span
						className={`min-w-0 flex-1 truncate font-mono ${selected ? "" : "text-zinc-400 dark:text-zinc-600"}`}
					>
						{selected ? fileNameOf(selected) : "選擇歷史模型…"}
					</span>
					<ChevronDown
						size={14}
						className={`shrink-0 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`}
					/>
				</button>

				{open && menuPos && (
					<ul
						id="recent-model-menu"
						style={{
							position: "fixed",
							top: menuPos.top,
							left: menuPos.left,
							width: menuPos.width,
						}}
						className="z-[300] max-h-48 overflow-y-auto overflow-x-hidden rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-xl shadow-zinc-900/10 dark:shadow-black/40 py-1 ring-1 ring-black/5"
						role="listbox"
					>
						{recentModels.map((p) => {
							const name = fileNameOf(p);
							const active = p === selected;
							return (
								<li key={p} role="option" aria-selected={active}>
									<button
										type="button"
										title={p}
										onClick={() => {
											setModelPath(p);
											setOpen(false);
										}}
										className={`w-full min-w-0 flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] font-mono transition-colors ${
											active
												? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
												: "text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
										}`}
									>
										<span className="min-w-0 flex-1 truncate">{name}</span>
										{active && <Check size={12} className="shrink-0" />}
									</button>
								</li>
							);
						})}
					</ul>
				)}
			</div>
		</div>
	);
}

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

	const inputClass =
		"w-full min-w-0 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-xl px-2.5 py-1.5 text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono placeholder:text-zinc-400 dark:placeholder:text-zinc-600 disabled:opacity-50";

	return (
		<div className="bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 space-y-3 shadow-sm shadow-zinc-900/5 dark:shadow-emerald-500/5 ring-1 ring-black/[0.02] dark:ring-white/[0.03] min-w-0 overflow-hidden">
			<div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
				<span className="flex items-center gap-1.5">
					<Cpu size={14} /> LLM 客戶端配置
				</span>
				<button
					type="button"
					onClick={checkServerHealth}
					disabled={isModelLoading}
					className="hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors disabled:opacity-40"
					title="重置與檢查連線"
				>
					<RefreshCw size={12} className={isModelLoading ? "animate-spin" : ""} />
				</button>
			</div>

			{/* 模式切換 */}
			<div className="grid grid-cols-2 gap-1.5">
				{CLIENT_MODES.map((m) => (
					<button
						key={m.value}
						type="button"
						onClick={() => setClientMode(m.value)}
						disabled={isModelLoading}
						title={m.hint}
						className={`flex flex-col items-center gap-1 py-2 px-1 rounded-xl text-[10px] font-medium border transition-all active:scale-[0.97] ${
							clientMode === m.value
								? "bg-emerald-500/10 border-emerald-500/40 text-emerald-700 dark:text-emerald-300"
								: "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-700 dark:hover:text-zinc-200"
						} ${isModelLoading ? "opacity-50 cursor-not-allowed" : ""}`}
					>
						{m.icon}
						{m.label}
					</button>
				))}
			</div>

			<p className="text-[10px] text-zinc-500 dark:text-zinc-500 leading-relaxed transition-opacity duration-200">
				{activeClientMode?.hint}
			</p>

			{/* local / remote 表單切換動畫 */}
			<div
				key={clientMode}
				className="min-w-0 animate-[panel-swap_0.28s_cubic-bezier(0.22,1,0.36,1)]"
			>
				{clientMode === "local_llama" && (
					<div className="space-y-2.5 min-w-0">
						{recentModels.length > 0 && (
							<RecentModelPicker
								recentModels={recentModels}
								modelPath={modelPath}
								setModelPath={setModelPath}
								disabled={isModelLoading}
								onClear={onClearRecentModels}
							/>
						)}

						<div className="space-y-1 min-w-0">
							<label className="text-[11px] text-zinc-500 dark:text-zinc-400">
								GGUF 模型檔案路徑
							</label>
							<div className="relative flex items-center min-w-0">
								<input
									type="text"
									value={modelPath}
									onChange={(e) => setModelPath(e.target.value)}
									disabled={isModelLoading}
									placeholder="C:\path\to\model.gguf"
									title={modelPath}
									className={`${inputClass} pl-2.5 pr-8 truncate`}
								/>
								{onPickModelFile && (
									<button
										type="button"
										onClick={onPickModelFile}
										disabled={isModelLoading}
										className="absolute right-2 text-zinc-400 dark:text-zinc-500 hover:text-zinc-600 dark:hover:text-zinc-300 disabled:opacity-40 transition-colors"
										title="瀏覽本機檔案"
									>
										<FolderOpen size={14} />
									</button>
								)}
							</div>
						</div>
					</div>
				)}

				{clientMode === "remote_api" && (
					<div className="space-y-2 min-w-0">
						<div className="space-y-1 min-w-0">
							<label className="text-[11px] text-zinc-500 dark:text-zinc-400">
								API Base URL
							</label>
							<input
								type="text"
								value={baseUrl}
								onChange={(e) => setBaseUrl(e.target.value)}
								className={inputClass}
							/>
						</div>

						<div className="space-y-1 min-w-0">
							<label className="text-[11px] text-zinc-500 dark:text-zinc-400">
								API Key
							</label>
							<input
								type="password"
								value={apiKey}
								onChange={(e) => setApiKey(e.target.value)}
								placeholder="sk-..."
								className={inputClass}
							/>
						</div>

						<div className="space-y-1 min-w-0">
							<label className="text-[11px] text-zinc-500 dark:text-zinc-400">
								Model Name
							</label>
							<input
								type="text"
								value={modelName}
								onChange={(e) => setModelName(e.target.value)}
								className={inputClass}
							/>
						</div>
					</div>
				)}
			</div>

			{clientMode === "local_llama" && isModelLoading && (
				<div className="bg-emerald-50/80 dark:bg-zinc-950/80 border border-emerald-500/30 rounded-xl p-2.5 space-y-2">
					<div className="flex items-center justify-between text-[11px]">
						<span className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-medium">
							<Loader2 size={13} className="animate-spin" />
							載入模型中...
						</span>
						<span className="text-[10px] text-zinc-500">配置顯存與權重</span>
					</div>
					<div className="h-1.5 w-full bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
						<div className="h-full bg-gradient-to-r from-emerald-500 via-teal-400 to-emerald-500 rounded-full animate-pulse w-full" />
					</div>
					<p className="text-[10px] text-zinc-500 dark:text-zinc-400 leading-tight">
						模型權重載入可能需要數秒至數十秒，完成後將自動轉為綠燈。
					</p>
				</div>
			)}

			<button
				type="button"
				onClick={applyApiConfig}
				disabled={isModelLoading}
				className={`w-full font-medium py-1.5 rounded-xl text-xs shadow-sm transition-all active:scale-[0.98] flex items-center justify-center gap-1.5 ${
					isModelLoading
						? "bg-zinc-200 dark:bg-zinc-800 text-zinc-400 cursor-not-allowed"
						: "bg-zinc-800 hover:bg-zinc-900 dark:bg-zinc-100 dark:hover:bg-white text-zinc-50 dark:text-zinc-950"
				}`}
			>
				{isModelLoading && <Loader2 size={13} className="animate-spin" />}
				{isModelLoading
					? "模型載入中..."
					: clientMode === "local_llama"
						? "載入模型"
						: "套用連線設定"}
			</button>

			{loadMessage && (
				<p
					className={`text-[11px] leading-relaxed ${
						loadMessage.type === "error"
							? "text-rose-500"
							: loadMessage.type === "success"
								? "text-emerald-600 dark:text-emerald-400"
								: "text-zinc-500 dark:text-zinc-400"
					}`}
				>
					{loadMessage.text}
				</p>
			)}

			<div className="flex items-center justify-between text-xs pt-2 border-t border-zinc-200/80 dark:border-zinc-800/80 min-w-0 gap-2">
				<span className="text-zinc-500 dark:text-zinc-400 shrink-0">狀態</span>
				<span className="flex items-center gap-1.5 font-medium min-w-0">
					<span
						className={`w-2 h-2 rounded-full shrink-0 ${serverStatus.running ? "bg-emerald-500 animate-pulse" : "bg-rose-500"}`}
					/>
					<span
						className={`truncate ${
							serverStatus.running
								? "text-zinc-700 dark:text-zinc-200"
								: "text-zinc-500 dark:text-zinc-400"
						}`}
						title={serverStatus.msg}
					>
						{serverStatus.msg}
					</span>
				</span>
			</div>
		</div>
	);
}
