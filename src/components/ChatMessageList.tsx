import type { RefObject } from "react";
import type {
	ChatMessage as ChatMessageType,
	ForkDirection,
	PermissionDecision,
} from "../types";
import ChatMessage from "./ChatMessage";

type ChatMessageListProps = {
	messages: ChatMessageType[];
	waitingConfirm: boolean;
	onConfirmStep: () => void;
	onCopy: (text: string) => Promise<void> | void;
	onSwitchFork: (msgId: string, direction: ForkDirection) => void;
	onEditUser: (
		msg: ChatMessageType,
		nextText: string,
		resend: boolean,
	) => void;
	onRespondPermission: (msgId: string, decision: PermissionDecision) => void;
	scrollContainerRef: RefObject<HTMLDivElement | null>;
	chatEndRef: RefObject<HTMLDivElement | null>;
	onScroll: () => void;
};

/**
 * 可捲動的訊息列表區域：捲動容器 + 逐則 ChatMessage + 捲動錨點。
 * 從 App.tsx 拆出來，讓 App 不用直接處理「怎麼把 messages 陣列渲染成畫面」
 * 這件跟版面佈局、狀態管理無關的事。
 */
export default function ChatMessageList({
	messages,
	waitingConfirm,
	onConfirmStep,
	onCopy,
	onSwitchFork,
	onEditUser,
	onRespondPermission,
	scrollContainerRef,
	chatEndRef,
	onScroll,
}: ChatMessageListProps) {
	return (
		<div
			ref={scrollContainerRef}
			onScroll={onScroll}
			className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-5 md:px-6"
		>
			{messages.map((msg, i) => (
				<ChatMessage
					key={msg.id || i}
					msg={msg}
					isLast={i === messages.length - 1}
					waitingConfirm={waitingConfirm}
					onConfirmStep={onConfirmStep}
					onCopy={onCopy}
					onSwitchFork={onSwitchFork}
					onEditUser={onEditUser}
					onRespondPermission={onRespondPermission}
				/>
			))}
			<div ref={chatEndRef} />
		</div>
	);
}
