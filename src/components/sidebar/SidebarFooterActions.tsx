import {
	ChevronDown,
	ChevronUp,
	Eraser,
	Eye,
	EyeOff,
	Terminal,
	Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

type SidebarFooterActionsProps = {
	isCollapsed: boolean;
	clearDrawings: () => void;
	clearHistory: () => void;
	showLogWindow: boolean;
	setShowLogWindow: (show: boolean) => void;
	preloadVisionModels?: () => void | Promise<unknown>;
	unloadVisionModels?: () => void | Promise<unknown>;
};

export default function SidebarFooterActions({
	isCollapsed,
	clearDrawings,
	clearHistory,
	showLogWindow,
	setShowLogWindow,
	preloadVisionModels,
	unloadVisionModels,
}: SidebarFooterActionsProps) {
	const [open, setOpen] = useState(false);
	const [busy, setBusy] = useState<"preload" | "unload" | null>(null);
	const [status, setStatus] = useState<{
		type: "info" | "success" | "error";
		text: string;
	} | null>(null);

	// 側欄收合時一併關掉工具選單，避免窄欄仍佔一堆高度
	useEffect(() => {
		if (isCollapsed) setOpen(false);
	}, [isCollapsed]);

	const buttonClass = `flex items-center justify-center gap-2 bg-white/70 dark:bg-zinc-900/80 hover:bg-zinc-100 dark:hover:bg-zinc-800 border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 rounded-xl text-xs transition-all duration-200 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed ${
		isCollapsed ? "p-2.5 w-10" : "w-full py-2"
	}`;

	const showStatus = (
		type: "info" | "success" | "error",
		text: string,
		ms = 3500,
	) => {
		setStatus({ type, text });
		window.setTimeout(() => setStatus(null), ms);
	};

	const handlePreload = async () => {
		if (!preloadVisionModels || busy) return;
		setBusy("preload");
		showStatus("info", "正在背景預載視覺模型…", 8000);
		try {
			await Promise.resolve(preloadVisionModels());
			showStatus("success", "已開始預載，完成後可即時分析圖片");
		} catch (e) {
			showStatus(
				"error",
				`預載失敗：${e instanceof Error ? e.message : String(e)}`,
			);
		} finally {
			setBusy(null);
		}
	};

	const handleUnload = async () => {
		if (!unloadVisionModels || busy) return;
		setBusy("unload");
		showStatus("info", "正在釋放視覺模型顯存…", 8000);
		try {
			const result = await Promise.resolve(unloadVisionModels());
			const msg =
				result &&
				typeof result === "object" &&
				"msg" in result &&
				typeof (result as { msg: unknown }).msg === "string"
					? (result as { msg: string }).msg
					: "視覺模型顯存已釋放";
			showStatus("success", msg);
		} catch (e) {
			showStatus(
				"error",
				`釋放失敗：${e instanceof Error ? e.message : String(e)}`,
			);
		} finally {
			setBusy(null);
		}
	};

	const statusClass =
		status?.type === "success"
			? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
			: status?.type === "error"
				? "bg-rose-50 dark:bg-rose-950/40 border-rose-500/30 text-rose-700 dark:text-rose-300"
				: "bg-zinc-100 dark:bg-zinc-800/60 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300";

	const expanded = open;

	return (
		<div
			className={`mt-auto w-full pt-2 border-t border-zinc-200/80 dark:border-zinc-800/80 ${isCollapsed ? "flex flex-col items-center" : ""}`}
		>
			{/* 收合標題列：展開側欄時顯示文字；收合側欄時只顯示 chevron */}
			{!isCollapsed ? (
				<button
					type="button"
					onClick={() => setOpen((v) => !v)}
					className="flex w-full items-center justify-between px-1 py-1.5 text-[11px] font-medium text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
				>
					<span>工具與維護</span>
					{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
				</button>
			) : (
				<button
					type="button"
					onClick={() => setOpen((v) => !v)}
					className="p-1.5 rounded-xl text-zinc-500 dark:text-zinc-400 hover:bg-zinc-200/80 dark:hover:bg-zinc-800 transition-colors mb-1"
					title={open ? "收合工具" : "展開工具"}
				>
					{open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
				</button>
			)}

			{status && !isCollapsed && expanded && (
				<div
					className={`mb-2 text-[10px] px-2.5 py-1.5 rounded-xl border leading-tight ${statusClass}`}
				>
					{status.text}
				</div>
			)}

			{/* 只有 open 時展開；側欄收合不會強制展開 */}
			<div
				className={`grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] ${
					expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
				}`}
			>
				<div className="min-h-0 overflow-hidden">
					<div
						className={`space-y-2 pt-1 ${isCollapsed ? "flex flex-col items-center" : ""}`}
					>
						{preloadVisionModels && (
							<button
								type="button"
								onClick={handlePreload}
								disabled={!!busy}
								className={buttonClass}
								title="預先載入 Florence-2 / PaddleOCR 視覺模型"
							>
								<Eye size={14} />
								{!isCollapsed &&
									(busy === "preload" ? "預載中…" : "預載視覺模型")}
							</button>
						)}

						{unloadVisionModels && (
							<button
								type="button"
								onClick={handleUnload}
								disabled={!!busy}
								className={buttonClass}
								title="釋放 Florence-2 / PaddleOCR 佔用的顯存"
							>
								<EyeOff size={14} />
								{!isCollapsed &&
									(busy === "unload" ? "釋放中…" : "釋放視覺顯存")}
							</button>
						)}

						<button
							type="button"
							onClick={clearDrawings}
							className={buttonClass}
							title="清除螢幕標記"
						>
							<Eraser size={14} /> {!isCollapsed && "清除螢幕標記"}
						</button>

						<button
							type="button"
							onClick={clearHistory}
							className={buttonClass}
							title="清空對話紀錄"
						>
							<Trash2 size={14} /> {!isCollapsed && "清空對話紀錄"}
						</button>

						<button
							type="button"
							onClick={() => setShowLogWindow(!showLogWindow)}
							className={buttonClass}
							title="切換面板 Log"
						>
							<Terminal size={14} />{" "}
							{!isCollapsed &&
								(showLogWindow ? "關閉面板 Log" : "開啟面板 Log")}
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}
