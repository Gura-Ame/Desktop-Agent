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

/** 滑鼠移過訊息時浮現在右上角的操作列：agent 訊息顯示複製、user 訊息顯示編輯。
 * 兩種按鈕互斥（同一則訊息不可能同時是 user 又是 agent），拆成一個元件用條件式
 * 決定要不要渲染，比原本兩段各自內嵌的 JSX 更容易一眼看出「這裡到底有什麼按鈕」。
 */
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
		<div className="absolute right-2 top-2 flex gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
			{showCopy && (
				<button
					type="button"
					onClick={onCopyClick}
					title={copied ? "已複製" : "複製內容"}
					className={cn(
						"rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200",
						copied && "text-emerald-600 dark:text-emerald-400",
					)}
				>
					{copied ? <Check size={13} /> : <Copy size={13} />}
				</button>
			)}
			{showEdit && (
				<button
					type="button"
					onClick={onStartEdit}
					title="編輯"
					className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 dark:text-zinc-500 dark:hover:bg-zinc-200 dark:hover:text-zinc-900"
				>
					<Pencil size={13} />
				</button>
			)}
		</div>
	);
}
