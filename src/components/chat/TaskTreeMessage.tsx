import { formatTimeLabel } from "../../lib/formatTime";
import TaskTreeCard from "../TaskTreeCard";
import MessageAvatar from "./MessageAvatar";

type TaskTreeMessageProps = {
	content: string;
	ts?: number;
	waitingConfirm: boolean;
	onConfirmStep: () => void;
};

/** msg.isTree === true 時的訊息渲染：一則「agent 頭像 + TaskTreeCard」的列，
 * 從 ChatMessage.tsx 拆出來，讓那個檔案不用同時處理兩種完全不同的訊息形狀。
 */
export default function TaskTreeMessage({
	content,
	ts,
	waitingConfirm,
	onConfirmStep,
}: TaskTreeMessageProps) {
	const treeTime = formatTimeLabel(ts);
	return (
		<div className="mx-auto flex max-w-3xl min-w-0 gap-3 justify-start">
			<MessageAvatar role="agent" />
			<div className="min-w-0 max-w-[min(85%,42rem)] flex-1 space-y-1">
				{treeTime && (
					<span className="px-1 text-[10px] tabular-nums text-zinc-400">
						{treeTime}
					</span>
				)}
				<TaskTreeCard
					markdown={content}
					waitingConfirm={waitingConfirm}
					onConfirmStep={onConfirmStep}
				/>
			</div>
		</div>
	);
}
