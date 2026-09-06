import { RotateCcw, Save, X } from "lucide-react";
import { cn } from "../../lib/utils";
import MarkdownBody from "./MarkdownBody";

type MessageEditFormProps = {
	draft: string;
	onDraftChange: (value: string) => void;
	onSave: (resend: boolean) => void;
	onCancel: () => void;
};

function looksLikeCodeOrMath(text: string): boolean {
	return (
		text.includes("```") ||
		text.includes("$") ||
		text.includes("\\(") ||
		text.includes("\\[")
	);
}

/** 使用者訊息編輯：獨立卡片，不嵌在原本的深色泡泡裡 */
export default function MessageEditForm({
	draft,
	onDraftChange,
	onSave,
	onCancel,
}: MessageEditFormProps) {
	return (
		<div
			className={cn(
				"w-full min-w-[min(100%,20rem)] space-y-2.5 rounded-2xl border p-3 shadow-md",
				"border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900",
				"animate-[msg-in_0.22s_ease-out]",
			)}
		>
			<textarea
				value={draft}
				onChange={(e) => onDraftChange(e.target.value)}
				rows={Math.min(10, Math.max(3, draft.split("\n").length + 1))}
				autoFocus
				className={cn(
					"w-full resize-y rounded-xl border px-3 py-2.5 text-sm leading-relaxed outline-none transition-shadow duration-200",
					"border-zinc-200 bg-zinc-50 text-zinc-900 placeholder:text-zinc-400",
					"focus:border-emerald-500/60 focus:bg-white focus:ring-2 focus:ring-emerald-500/20",
					"dark:border-zinc-600 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-500",
					"dark:focus:border-emerald-400/50 dark:focus:bg-zinc-950 dark:focus:ring-emerald-400/15",
				)}
			/>
			{looksLikeCodeOrMath(draft) && (
				<div
					className={cn(
						"rounded-xl border p-2.5 animate-[fade-in_0.2s_ease-out]",
						"border-zinc-100 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950/80",
					)}
				>
					<div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
						Preview
					</div>
					<div className="text-zinc-800 dark:text-zinc-200">
						<MarkdownBody content={draft} />
					</div>
				</div>
			)}
			<div className="flex flex-wrap items-center gap-1.5">
				<button
					type="button"
					onClick={() => onSave(true)}
					title="修改內容並建立分枝，重新向模型產生回覆"
					className={cn(
						"inline-flex h-8 items-center gap-1.5 rounded-xl px-3 text-xs font-medium transition-all duration-150 active:scale-[0.97]",
						"bg-emerald-600 text-white shadow-sm shadow-emerald-600/20 hover:bg-emerald-500",
						"dark:bg-emerald-500 dark:text-zinc-950 dark:hover:bg-emerald-400",
					)}
				>
					<RotateCcw size={13} />
					儲存並重送
				</button>
				<button
					type="button"
					onClick={() => onSave(false)}
					title="只改畫面上的這則文字，不呼叫模型、不重產回覆（適合改錯字）"
					className={cn(
						"inline-flex h-8 items-center gap-1.5 rounded-xl border px-3 text-xs font-medium transition-all duration-150 active:scale-[0.97]",
						"border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50",
						"dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700",
					)}
				>
					<Save size={13} />
					僅儲存
				</button>
				<button
					type="button"
					onClick={onCancel}
					className={cn(
						"inline-flex h-8 items-center gap-1 rounded-xl px-2.5 text-xs font-medium transition-all duration-150 active:scale-[0.97]",
						"text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800",
						"dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100",
					)}
				>
					<X size={14} />
					取消
				</button>
			</div>
		</div>
	);
}
