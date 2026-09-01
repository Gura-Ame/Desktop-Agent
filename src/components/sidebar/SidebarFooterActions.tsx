import { Eraser, Terminal, Trash2 } from "lucide-react";

type SidebarFooterActionsProps = {
	isCollapsed: boolean;
	clearDrawings: () => void;
	clearHistory: () => void;
	showLogWindow: boolean;
	setShowLogWindow: (show: boolean) => void;
};

export default function SidebarFooterActions({
	isCollapsed,
	clearDrawings,
	clearHistory,
	showLogWindow,
	setShowLogWindow,
}: SidebarFooterActionsProps) {
	const buttonClass = `flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 rounded-lg text-xs transition-all active:scale-[0.98] ${
		isCollapsed ? "p-2.5 w-10" : "w-full py-2"
	}`;

	return (
		<div
			className={`mt-auto space-y-2 w-full pt-2 border-t border-zinc-800/80 ${isCollapsed ? "flex flex-col items-center" : ""}`}
		>
			<button
				onClick={clearDrawings}
				className={buttonClass}
				title="清除螢幕標記"
			>
				<Eraser size={14} /> {!isCollapsed && "清除螢幕標記"}
			</button>

			<button onClick={clearHistory} className={buttonClass} title="清空對話紀錄">
				<Trash2 size={14} /> {!isCollapsed && "清空對話紀錄"}
			</button>

			<button
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
