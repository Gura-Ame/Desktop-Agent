import { Eraser, Eye, EyeOff, Terminal, Trash2 } from "lucide-react";

type SidebarFooterActionsProps = {
	isCollapsed: boolean;
	clearDrawings: () => void;
	clearHistory: () => void;
	showLogWindow: boolean;
	setShowLogWindow: (show: boolean) => void;
	preloadVisionModels?: () => void;
	unloadVisionModels?: () => void;
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
	const buttonClass = `flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 rounded-lg text-xs transition-all active:scale-[0.98] ${
		isCollapsed ? "p-2.5 w-10" : "w-full py-2"
	}`;

	return (
		<div
			className={`mt-auto space-y-2 w-full pt-2 border-t border-zinc-800/80 ${isCollapsed ? "flex flex-col items-center" : ""}`}
		>
			{preloadVisionModels && (
				<button
					type="button"
					onClick={preloadVisionModels}
					className={buttonClass}
					title="預先載入 Florence-2 / PaddleOCR 視覺模型（背景載入不卡頓，後續分析圖片可即時回應）"
				>
					<Eye size={14} className="text-sky-400" />{" "}
					{!isCollapsed && "預載視覺模型"}
				</button>
			)}

			{unloadVisionModels && (
				<button
					type="button"
					onClick={unloadVisionModels}
					className={buttonClass}
					title="釋放 Florence-2 / PaddleOCR 佔用的顯存 (VRAM) 與記憶體"
				>
					<EyeOff size={14} className="text-amber-400" />{" "}
					{!isCollapsed && "釋放視覺顯存"}
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
				{!isCollapsed && (showLogWindow ? "關閉面板 Log" : "開啟面板 Log")}
			</button>
		</div>
	);
}
