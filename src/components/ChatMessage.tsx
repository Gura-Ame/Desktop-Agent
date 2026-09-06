import { useState } from "react";
import { formatTimeLabel } from "../lib/formatTime";
import { parseMessageContent } from "../lib/parseMessage";
import { cn } from "../lib/utils";
import type {
	ChatMessage as ChatMessageType,
	ForkDirection,
	PermissionDecision,
} from "../types";
import MessageActions from "./chat/MessageActions";
import MessageAvatar from "./chat/MessageAvatar";
import MessageBody from "./chat/MessageBody";
import MessageEditForm from "./chat/MessageEditForm";
import MessageFileAttachments from "./chat/MessageFileAttachments";
import MessageForksNav from "./chat/MessageForksNav";
import MessageImageAttachments from "./chat/MessageImageAttachments";
import PermissionRequestMessage from "./chat/PermissionRequestMessage";
import TaskTreeMessage from "./chat/TaskTreeMessage";

function plainTextForCopy(content: string | undefined) {
	if (!content) return "";
	return content
		.replace(/<\|tool_call\|>[\s\S]*?(?:<\/?\|?tool_call\|?>|$)/g, "")
		.replace(/<\/?tool_result>/g, "")
		.replace(/<\/?tool_error>/g, "")
		.trim();
}

type ChatMessageProps = {
	msg: ChatMessageType;
	isLast: boolean;
	waitingConfirm: boolean;
	onConfirmStep: () => void;
	onCopy?: (text: string) => Promise<void> | void;
	onEditUser?: (
		msg: ChatMessageType,
		nextText: string,
		resend: boolean,
	) => void;
	onSwitchFork?: (msgId: string, direction: ForkDirection) => void;
	onRespondPermission?: (msgId: string, decision: PermissionDecision) => void;
};

export default function ChatMessage({
	msg,
	isLast,
	waitingConfirm,
	onConfirmStep,
	onCopy,
	onEditUser,
	onSwitchFork,
	onRespondPermission,
}: ChatMessageProps) {
	const isUser = msg.role === "user";
	const [copied, setCopied] = useState(false);
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState(msg.content || "");
	const forkCount = msg.forks?.length || 0;
	const forkIndex = msg.forkIndex ?? 0;

	if (msg.isTree) {
		return (
			<TaskTreeMessage
				content={msg.content}
				ts={msg.ts}
				waitingConfirm={waitingConfirm && isLast}
				onConfirmStep={onConfirmStep}
			/>
		);
	}

	if (msg.isPermissionRequest && msg.permissionInfo) {
		return (
			<PermissionRequestMessage
				info={msg.permissionInfo}
				resolved={msg.permissionResolved}
				onRespond={(decision) => onRespondPermission?.(msg.id, decision)}
			/>
		);
	}

	if (!isUser && msg.isStreaming && !msg.content?.trim()) {
		return null;
	}

	const blocks = parseMessageContent(msg.content, {
		isStreaming: !!msg.isStreaming,
	});

	const handleCopyClick = async () => {
		const text = plainTextForCopy(msg.content);
		if (!text || !onCopy) return;
		await onCopy(text);
		setCopied(true);
		setTimeout(() => setCopied(false), 1500);
	};

	const saveEdit = (resend: boolean) => {
		const next = draft.trim();
		if (!next) return;
		onEditUser?.(msg, next, resend);
		setEditing(false);
	};

	const timeLabel = formatTimeLabel(msg.ts);

	return (
		<div
			className={cn(
				"group mx-auto flex max-w-3xl min-w-0 gap-3 animate-[msg-in_0.28s_ease-out]",
				isUser ? "justify-end" : "justify-start",
			)}
		>
			{!isUser && <MessageAvatar role="agent" />}

			<div
				className={cn(
					"flex min-w-0 max-w-[min(85%,42rem)] flex-col gap-1",
					isUser && "items-end",
				)}
			>
				{isUser && (
					<MessageForksNav
						msgId={msg.id}
						forkIndex={forkIndex}
						forkCount={forkCount}
						onSwitchFork={onSwitchFork}
					/>
				)}

				{editing ? (
					/* 編輯時整塊換成獨立表單，不要嵌在深色泡泡裡 */
					<MessageEditForm
						draft={draft}
						onDraftChange={setDraft}
						onSave={saveEdit}
						onCancel={() => {
							setEditing(false);
							setDraft(msg.content || "");
						}}
					/>
				) : (
					<div
						className={cn(
							"relative chat-selectable min-w-0 rounded-2xl text-sm leading-relaxed transition-shadow duration-200",
							isUser
								? "rounded-br-md bg-zinc-700 px-3.5 py-2 text-zinc-50 dark:bg-zinc-600 dark:text-zinc-50"
								: "rounded-bl-md border border-zinc-300 bg-[#f0f0f2] px-3.5 py-2.5 text-zinc-800 dark:border-[#3a3a3c] dark:bg-[#242426] dark:text-zinc-200",
						)}
					>
						<MessageImageAttachments images={msg.images} />
						<MessageFileAttachments files={msg.files} />

						<div
							className={cn(
								"chat-selectable min-w-0 space-y-1.5 overflow-x-auto break-words",
								isUser && "whitespace-pre-wrap",
							)}
						>
							<MessageBody
								isUser={isUser}
								rawContent={msg.content}
								blocks={blocks}
								isStreaming={msg.isStreaming}
							/>
						</div>
					</div>
				)}

				{/* 時間戳 + 複製／編輯 都在訊息下方 */}
				<div
					className={cn(
						"flex items-center gap-1.5",
						isUser ? "flex-row-reverse" : "flex-row",
					)}
				>
					{timeLabel && (
						<span className="px-0.5 text-[10px] tabular-nums text-zinc-400">
							{timeLabel}
						</span>
					)}
					{!editing && (
						<MessageActions
							isUser={isUser}
							isStreaming={msg.isStreaming}
							hasContent={!!msg.content}
							copied={copied}
							onCopyClick={handleCopyClick}
							editing={editing}
							canEdit={!!onEditUser}
							onStartEdit={() => {
								setDraft(msg.content || "");
								setEditing(true);
							}}
						/>
					)}
				</div>
			</div>

			{isUser && <MessageAvatar role="user" />}
		</div>
	);
}
