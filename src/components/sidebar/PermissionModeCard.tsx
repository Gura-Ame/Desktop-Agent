import { ShieldCheck } from "lucide-react";
import type { PermissionMode } from "../../types";
import { PERMISSION_MODE_OPTIONS } from "./constants";

type PermissionModeCardProps = {
	permissionMode: PermissionMode;
	handlePermissionModeChange: (mode: PermissionMode) => void;
};

/** 各模式選中時的外框色（只改 border，背景保持中性） */
const BORDER_ACTIVE: Record<PermissionMode, string> = {
	ask: "border-sky-500 text-sky-700 dark:border-sky-400 dark:text-sky-300",
	ask_dangerous_only:
		"border-amber-500 text-amber-700 dark:border-amber-400 dark:text-amber-300",
	auto: "border-rose-500 text-rose-700 dark:border-rose-400 dark:text-rose-300",
};

/** 工具授權策略選擇——跟 ExecutionModeCard 是同一種三選一卡片樣式，
 * 但概念上完全不同：ExecutionMode 管的是 Task Tree 步驟之間要不要暫停，
 * 這裡管的是「單一工具呼叫」本身要不要先問過使用者才能執行
 * （agent/tool_permissions.py 的 PermissionMode，兩者互相獨立）。
 */
export default function PermissionModeCard({
	permissionMode,
	handlePermissionModeChange,
}: PermissionModeCardProps) {
	return (
		<div className="bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/80 dark:border-zinc-800 rounded-2xl p-3.5 space-y-3 shadow-sm shadow-zinc-900/5 dark:shadow-amber-500/5 ring-1 ring-black/[0.02] dark:ring-white/[0.03]">
			<div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
				<ShieldCheck size={14} /> 工具授權策略
			</div>

			<div className="grid grid-cols-3 gap-1.5">
				{PERMISSION_MODE_OPTIONS.map((opt) => {
					const isActive = permissionMode === opt.value;
					return (
						<button
							key={opt.value}
							type="button"
							onClick={() => handlePermissionModeChange(opt.value)}
							title={opt.hint}
							className={`py-2 rounded-xl text-[11px] font-medium border-2 transition-all active:scale-[0.98] ${
								isActive
									? `bg-zinc-50 dark:bg-zinc-950/60 ${BORDER_ACTIVE[opt.value]}`
									: "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
							}`}
						>
							{opt.label}
						</button>
					);
				})}
			</div>
			<p className="text-[11px] text-zinc-500 dark:text-zinc-500 leading-relaxed">
				{PERMISSION_MODE_OPTIONS.find((o) => o.value === permissionMode)
					?.hint || ""}
			</p>
		</div>
	);
}
