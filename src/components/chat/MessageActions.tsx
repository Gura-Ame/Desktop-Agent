import { Check, Copy, Pencil } from "lucide-react";
import { cn } from "../../lib/utils";

type MessageActionsProps = {
	isUser: boolean;
	isStreaming: boolean | undefined;
	hasContent: boolean;
	copied: boolean;
	onCopyClick: () => void;
	editing: boolean;
	canEdit: boolean;
	onStartEdit: () => void;
};

/** 訊息泡泡下方的操作列：複製／編輯（hover 才展開文字） */
export default function MessageActions({
	isUser,
	isStreaming,
	hasContent,
	copied,
	onCopyClick,
	editing,
	canEdit,
	onStartEdit,
}: MessageActionsProps) {
	const showCopy = !isUser && !isStreaming && hasContent;
	const showEdit = isUser && !editing && canEdit;
	if (!showCopy && !showEdit) return null;

	return (
		<div
			className={cn(
				"flex items-center gap-0.5 px-0.5",
				isUser ? "justify-end" : "justify-start",
			)}
		>
			{showCopy && (
				<button
					type="button"
					onClick={onCopyClick}
					title={copied ? "已複製" : "複製內容"}
					className={cn(
						"group/copy inline-flex items-center gap-0 overflow-hidden rounded-lg px-1.5 py-1 text-[11px] text-zinc-400 transition-all duration-200",
						"hover:bg-zinc-200/70 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200",
						copied && "text-emerald-600 dark:text-emerald-400",
					)}
				>
					{copied ? (
						<Check size={12} className="shrink-0" />
					) : (
						<Copy size={12} className="shrink-0" />
					)}
					<span
						className={cn(
							"max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-all duration-200",
							"group-hover/copy:ms-1 group-hover/copy:max-w-[3.5rem] group-hover/copy:opacity-100",
							copied && "ms-1 max-w-[3.5rem] opacity-100",
						)}
					>
						{copied ? "已複製" : "複製"}
					</span>
				</button>
			)}
			{showEdit && (
				<button
					type="button"
					onClick={onStartEdit}
					title="編輯"
					className={cn(
						"group/edit inline-flex items-center gap-0 overflow-hidden rounded-lg px-1.5 py-1 text-[11px] text-zinc-400 transition-all duration-200",
						"hover:bg-zinc-200/70 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200",
					)}
				>
					<Pencil size={12} className="shrink-0" />
					<span className="max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-all duration-200 group-hover/edit:ms-1 group-hover/edit:max-w-[3rem] group-hover/edit:opacity-100">
						編輯
					</span>
				</button>
			)}
		</div>
	);
}
