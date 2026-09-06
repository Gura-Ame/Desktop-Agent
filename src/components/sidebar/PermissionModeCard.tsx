import { ShieldCheck } from "lucide-react";
import type { PermissionMode } from "../../types";
import { PERMISSION_MODE_OPTIONS } from "./constants";

type PermissionModeCardProps = {
	permissionMode: PermissionMode;
	handlePermissionModeChange: (mode: PermissionMode) => void;
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
		<div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-3 shadow-sm">
			<div className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
				<ShieldCheck size={14} /> 工具授權策略
			</div>

			<div className="grid grid-cols-3 gap-1.5">
				{PERMISSION_MODE_OPTIONS.map((opt) => (
					<button
						key={opt.value}
						onClick={() => handlePermissionModeChange(opt.value)}
						title={opt.hint}
						className={`py-2 rounded-lg text-[11px] font-medium border transition-all active:scale-[0.98] ${
							permissionMode === opt.value
								? "bg-amber-500 border-amber-400 text-zinc-950"
								: "bg-zinc-950 border-zinc-800 text-zinc-300 hover:bg-zinc-800"
						}`}
					>
						{opt.label}
					</button>
				))}
			</div>
			<p className="text-[11px] text-zinc-500 leading-relaxed">
				{PERMISSION_MODE_OPTIONS.find((o) => o.value === permissionMode)
					?.hint || ""}
			</p>
		</div>
	);
}
