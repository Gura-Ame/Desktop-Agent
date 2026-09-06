import type { MessageBlock } from "../../types";
import MarkdownBody from "./MarkdownBody";
import ToolCallBlock from "../ToolCallBlock";

type MessageBodyProps = {
	isUser: boolean;
	rawContent: string | undefined;
	blocks: MessageBlock[];
	isStreaming: boolean | undefined;
};

/** 訊息的實際內容：user 訊息就是純文字；agent 訊息要把 parseMessageContent
 * 切出來的 blocks 逐一渲染成工具呼叫卡片或 Markdown，並在還在串流時補一個
 * 閃爍的游標。這塊原本直接寫在 ChatMessage.tsx 裡的 JSX 中間，跟編輯表單的
 * JSX 交錯在一起，拆開後兩邊都變得比較好讀。
 */
export default function MessageBody({
	isUser,
	rawContent,
	blocks,
	isStreaming,
}: MessageBodyProps) {
	if (isUser) return <>{rawContent}</>;

	return (
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
			{isStreaming && (
				<span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-zinc-400 align-middle dark:bg-zinc-500" />
			)}
		</>
	);
}
