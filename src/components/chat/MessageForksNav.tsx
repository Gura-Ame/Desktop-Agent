import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ForkDirection } from "../../types";

type MessageForksNavProps = {
	msgId: string;
	forkIndex: number;
	forkCount: number;
	onSwitchFork?: (msgId: string, direction: ForkDirection) => void;
};

export default function MessageForksNav({
	msgId,
	forkIndex,
	forkCount,
	onSwitchFork,
}: MessageForksNavProps) {
	if (!forkCount || forkCount <= 1) return null;

	return (
		<div className="flex items-center justify-end gap-1 px-1">
			<button
				type="button"
				onClick={() => onSwitchFork?.(msgId, "prev")}
				className="rounded p-0.5 text-zinc-400 hover:bg-zinc-300/50 hover:text-zinc-700 dark:hover:bg-zinc-700/50 dark:hover:text-zinc-200"
				title="上一個分枝"
			>
				<ChevronLeft size={14} />
			</button>
			<span className="min-w-[2.5rem] text-center text-[10px] tabular-nums text-zinc-400">
				{forkIndex + 1} / {forkCount}
			</span>
			<button
				type="button"
				onClick={() => onSwitchFork?.(msgId, "next")}
				className="rounded p-0.5 text-zinc-400 hover:bg-zinc-300/50 hover:text-zinc-700 dark:hover:bg-zinc-700/50 dark:hover:text-zinc-200"
				title="下一個分枝"
			>
				<ChevronRight size={14} />
			</button>
		</div>
	);
}
