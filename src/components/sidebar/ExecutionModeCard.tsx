import { ListTree } from "lucide-react";
import type { ExecutionMode } from "../../types";
import { MODE_OPTIONS } from "./constants";

type ExecutionModeCardProps = {
	executionMode: ExecutionMode;
	handleModeChange: (mode: ExecutionMode) => void;
};

export default function ExecutionModeCard({
	executionMode,
	handleModeChange,
}: ExecutionModeCardProps) {
	return (
		<div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-3 shadow-sm">
			<div className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
				<ListTree size={14} /> Task Tree 執行模式
			</div>

			<div className="grid grid-cols-3 gap-1.5">
				{MODE_OPTIONS.map((opt) => (
					<button
						key={opt.value}
						onClick={() => handleModeChange(opt.value)}
						title={opt.hint}
						className={`py-2 rounded-lg text-[11px] font-medium border transition-all active:scale-[0.98] ${
							executionMode === opt.value
								? "bg-emerald-500 border-emerald-400 text-zinc-950"
								: "bg-zinc-950 border-zinc-800 text-zinc-300 hover:bg-zinc-800"
						}`}
					>
						{opt.label}
					</button>
				))}
			</div>
			<p className="text-[11px] text-zinc-500 leading-relaxed">
				{MODE_OPTIONS.find((o) => o.value === executionMode)?.hint ||
					"每完成一步就暫停，等待你確認才繼續"}
			</p>
		</div>
	);
}
