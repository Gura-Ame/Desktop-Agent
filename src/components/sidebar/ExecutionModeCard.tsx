import { ListTree } from "lucide-react";
import type { ExecutionMode } from "../../types";
import { MODE_OPTIONS } from "./constants";

type ExecutionModeCardProps = {
	executionMode: ExecutionMode;
	handleModeChange: (mode: ExecutionMode) => void;
};

/** 各模式選中色：逐步=琥珀、智慧=天空、全自動=翠绿 */
const MODE_ACTIVE: Record<ExecutionMode, string> = {
	STEP_BY_STEP:
		"bg-amber-500/15 border-amber-500 text-amber-800 shadow-amber-500/25 dark:bg-amber-500/20 dark:border-amber-400 dark:text-amber-200",
	SMART:
		"bg-sky-500/15 border-sky-500 text-sky-800 shadow-sky-500/25 dark:bg-sky-500/20 dark:border-sky-400 dark:text-sky-200",
	AUTO:
		"bg-emerald-500/15 border-emerald-500 text-emerald-800 shadow-emerald-500/25 dark:bg-emerald-500/20 dark:border-emerald-400 dark:text-emerald-200",
};

export default function ExecutionModeCard({
	executionMode,
	handleModeChange,
}: ExecutionModeCardProps) {
	return (
		<div className="rounded-2xl border border-zinc-200/80 bg-white/80 p-3.5 shadow-sm shadow-zinc-900/5 ring-1 ring-black/0 dark:border-zinc-800 dark:bg-zinc-900/80 dark:shadow-black/20 space-y-3">
			<div className="flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
				<ListTree size={14} /> Task Tree 執行模式
			</div>

			<div className="grid grid-cols-3 gap-1.5">
				{MODE_OPTIONS.map((opt) => {
					const active = executionMode === opt.value;
					return (
						<button
							key={opt.value}
							type="button"
							onClick={() => handleModeChange(opt.value)}
							title={opt.hint}
							className={`py-2 rounded-xl text-[11px] font-medium border-2 transition-all duration-200 active:scale-[0.98] ${
								active
									? `${MODE_ACTIVE[opt.value]} shadow-md`
									: "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
							}`}
						>
							{opt.label}
						</button>
					);
				})}
			</div>
			<p className="text-[11px] text-zinc-500 dark:text-zinc-500 leading-relaxed">
				{MODE_OPTIONS.find((o) => o.value === executionMode)?.hint ||
					"每完成一步就暫停，等待你確認才繼續"}
			</p>
		</div>
	);
}
