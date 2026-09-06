import { X } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "../ui/Button";
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

/** 使用者訊息的編輯狀態：文字框 + 有需要才顯示的即時預覽 + 儲存/取消按鈕。
 * 從 ChatMessage.tsx 拆出來單獨管理，是那個檔案裡邏輯最集中的一塊 UI，
 * 獨立出來後 ChatMessage 本身只需要知道「編不編輯中」跟「草稿內容」。
 */
export default function MessageEditForm({
	draft,
	onDraftChange,
	onSave,
	onCancel,
}: MessageEditFormProps) {
	return (
		<div className="space-y-2">
			<textarea
				value={draft}
				onChange={(e) => onDraftChange(e.target.value)}
				rows={4}
				className={cn(
					"w-full resize-y rounded-md border px-2 py-1.5 text-sm outline-none",
					"border-zinc-600 bg-zinc-950 text-zinc-100",
					"dark:border-zinc-300 dark:bg-white dark:text-zinc-900",
				)}
			/>
			{looksLikeCodeOrMath(draft) && (
				<div className="rounded-md border border-zinc-700/50 bg-zinc-950/50 p-2 dark:border-zinc-300 dark:bg-white/80">
					<div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
						Preview
					</div>
					<div className="text-zinc-200 dark:text-zinc-800">
						<MarkdownBody content={draft} />
					</div>
				</div>
			)}
			<div className="flex flex-wrap gap-1.5">
				<Button size="sm" variant="primary" onClick={() => onSave(false)}>
					儲存
				</Button>
				<Button size="sm" variant="default" onClick={() => onSave(true)}>
					儲存並重送
				</Button>
				<Button size="sm" variant="ghost" onClick={onCancel}>
					<X size={14} /> 取消
				</Button>
			</div>
		</div>
	);
}
