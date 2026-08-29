import { Bot, Check, Copy, Pencil, User, X } from "lucide-react";
import { useState } from "react";
import { parseMessageContent } from "../lib/parseMessage";
import { cn } from "../lib/utils";
import TaskTreeCard from "./TaskTreeCard";
import ToolCallBlock from "./ToolCallBlock";
import { Button } from "./ui/Button";
import MarkdownBody from "./chat/MarkdownBody";
import MessageForksNav from "./chat/MessageForksNav";
import type { ChatMessage as ChatMessageType, ForkDirection } from "../types";

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
};

export default function ChatMessage({
	msg,
	isLast,
	waitingConfirm,
	onConfirmStep,
	onCopy,
	onEditUser,
	onSwitchFork,
}: ChatMessageProps) {
	const isUser = msg.role === "user";
	const [copied, setCopied] = useState(false);
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState(msg.content || "");
	const forkCount = msg.forks?.length || 0;
	const forkIndex = msg.forkIndex ?? 0;

	// 任務樹
	if (msg.isTree) {
		const treeTime = msg.ts
			? new Date(msg.ts).toLocaleTimeString([], {
					hour: "2-digit",
					minute: "2-digit",
					second: "2-digit",
				})
			: null;
		return (
			<div className="mx-auto flex max-w-3xl min-w-0 gap-3 justify-start">
				<div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
					<Bot size={14} />
				</div>
				<div className="min-w-0 max-w-[min(85%,42rem)] flex-1 space-y-1">
					{treeTime && (
						<span className="px-1 text-[10px] tabular-nums text-zinc-400">
							{treeTime}
						</span>
					)}
					<TaskTreeCard
						markdown={msg.content}
						waitingConfirm={waitingConfirm && isLast}
						onConfirmStep={onConfirmStep}
					/>
				</div>
			</div>
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

	const timeLabel = msg.ts
		? new Date(msg.ts).toLocaleTimeString([], {
				hour: "2-digit",
				minute: "2-digit",
				second: "2-digit",
			})
		: null;

	return (
		<div
			className={cn(
				"group mx-auto flex max-w-3xl min-w-0 gap-3",
				isUser ? "justify-end" : "justify-start",
			)}
		>
			{!isUser && (
				<div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
					<Bot size={14} />
				</div>
			)}

			<div className="flex min-w-0 max-w-[min(85%,42rem)] flex-col gap-1">
				{timeLabel && (
					<span
						className={cn(
							"px-1 text-[10px] tabular-nums text-zinc-400",
							isUser ? "text-right" : "text-left",
						)}
					>
						{timeLabel}
					</span>
				)}

				{/* 分枝切換 */}
				{isUser && (
					<MessageForksNav
						msgId={msg.id}
						forkIndex={forkIndex}
						forkCount={forkCount}
						onSwitchFork={onSwitchFork}
					/>
				)}

				<div
					className={cn(
						"relative chat-selectable min-w-0 rounded-lg px-3.5 py-2.5 text-sm leading-relaxed",
						isUser
							? "rounded-br-sm bg-zinc-700 text-zinc-50 dark:bg-zinc-600 dark:text-zinc-50"
							: "rounded-bl-sm border border-zinc-300 bg-[#f0f0f2] text-zinc-800 dark:border-[#3a3a3c] dark:bg-[#242426] dark:text-zinc-200",
					)}
				>
					{/* 操作列：agent 複製 / user 編輯 */}
					<div
						className={cn(
							"absolute right-2 top-2 flex gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100",
						)}
					>
						{!isUser && !msg.isStreaming && msg.content && (
							<button
								type="button"
								onClick={handleCopyClick}
								title={copied ? "已複製" : "複製內容"}
								className={cn(
									"rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200",
									copied && "text-emerald-600 dark:text-emerald-400",
								)}
							>
								{copied ? <Check size={13} /> : <Copy size={13} />}
							</button>
						)}
						{isUser && !editing && onEditUser && (
							<button
								type="button"
								onClick={() => {
									setDraft(msg.content || "");
									setEditing(true);
								}}
								title="編輯"
								className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 dark:text-zinc-500 dark:hover:bg-zinc-200 dark:hover:text-zinc-900"
							>
								<Pencil size={13} />
							</button>
						)}
					</div>

					{!!msg.images?.length && (
						<div className="mb-2 flex flex-wrap gap-2">
							{msg.images.map((img) => (
								<a
									key={img.id || img.name}
									href={img.dataUrl}
									target="_blank"
									rel="noreferrer"
									className="block overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700"
								>
									<img
										src={img.dataUrl}
										alt={img.name || "attachment"}
										className="max-h-40 max-w-[200px] object-contain"
									/>
								</a>
							))}
						</div>
					)}

					{editing ? (
						<div className="space-y-2">
							<textarea
								value={draft}
								onChange={(e) => setDraft(e.target.value)}
								rows={4}
								className={cn(
									"w-full resize-y rounded-md border px-2 py-1.5 text-sm outline-none",
									"border-zinc-600 bg-zinc-950 text-zinc-100",
									"dark:border-zinc-300 dark:bg-white dark:text-zinc-900",
								)}
							/>
							{/* 即時預覽：程式碼 / 數學 */}
							{(draft.includes("```") ||
								draft.includes("$") ||
								draft.includes("\\(") ||
								draft.includes("\\[")) && (
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
								<Button
									size="sm"
									variant="primary"
									onClick={() => saveEdit(false)}
								>
									儲存
								</Button>
								<Button
									size="sm"
									variant="default"
									onClick={() => saveEdit(true)}
								>
									儲存並重送
								</Button>
								<Button
									size="sm"
									variant="ghost"
									onClick={() => {
										setEditing(false);
										setDraft(msg.content || "");
									}}
								>
									<X size={14} /> 取消
								</Button>
							</div>
						</div>
					) : (
						<div
							className={cn(
								"chat-selectable min-w-0 space-y-1.5 overflow-x-auto break-words",
								!isUser && "pr-7",
								isUser && "pr-7 whitespace-pre-wrap",
							)}
						>
							{isUser ? (
								msg.content
							) : (
								<>
									{blocks.map((block, idx) => {
										if (block.type === "tool") {
											return (
												<ToolCallBlock
													key={idx}
													funcName={block.funcName}
													args={block.args}
													result={block.result}
													status={block.status}
												/>
											);
										}
										return <MarkdownBody key={idx} content={block.content} />;
									})}
									{msg.isStreaming && (
										<span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-zinc-400 align-middle dark:bg-zinc-500" />
									)}
								</>
							)}
						</div>
					)}
				</div>
			</div>

			{isUser && (
				<div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
					<User size={14} />
				</div>
			)}
		</div>
	);
}
