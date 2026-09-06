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

	// 側欄收合時一併關掉工具選單
	useEffect(() => {
		if (isCollapsed) setOpen(false);
	}, [isCollapsed]);

	const buttonClass = `flex items-center justify-center gap-2 bg-white/70 dark:bg-zinc-900/80 hover:bg-zinc-100 dark:hover:bg-zinc-800 border border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 rounded-xl text-xs transition-all duration-200 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed ${
		isCollapsed ? "p-2.5 w-10" : "w-full py-2"
	}`;

	const handlePreload = async () => {
		if (!preloadVisionModels || busy) return;
		setBusy("preload");
		try {
			await Promise.resolve(preloadVisionModels());
		} finally {
			setBusy(null);
		}
	};

	const handleUnload = async () => {
		if (!unloadVisionModels || busy) return;
		setBusy("unload");
		try {
			await Promise.resolve(unloadVisionModels());
		} finally {
			setBusy(null);
		}
	};

	const expanded = open;

	return (
		<div
			className={`mt-auto w-full pt-2 border-t border-zinc-200/80 dark:border-zinc-800/80 ${isCollapsed ? "flex flex-col items-center" : ""}`}
		>
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
