import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage as ChatMessageType } from "../types";
import ChatMessage from "./ChatMessage";

// ChatMessage.tsx 被拆成好幾個 chat/* 子元件之後（MessageAvatar/MessageActions/
// MessageEditForm/MessageBody/MessageImageAttachments/TaskTreeMessage），
// 這裡驗證組裝起來的整體行為沒有跑掉——重點放在會牽涉多個子元件互動的路徑，
// 純 UI 呈現的細節交給各子元件自己的職責範圍。

function makeMsg(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
	return {
		id: "m1",
		role: "agent",
		content: "哈囉",
		ts: Date.now(),
		...overrides,
	};
}

describe("ChatMessage", () => {
	it("isTree 訊息會走 TaskTreeMessage 分支，不會被當成一般文字訊息", () => {
		const msg = makeMsg({
			isTree: true,
			content: "- [ ] [TASK-1] 標題\n  - 需要確認: NO\n",
		});
		render(
			<ChatMessage
				msg={msg}
				isLast={true}
				waitingConfirm={false}
				onConfirmStep={() => {}}
			/>,
		);
		expect(screen.getByText("標題")).toBeInTheDocument();
	});

	it("還在串流中且內容是空字串的 agent 訊息不渲染任何東西", () => {
		const msg = makeMsg({ content: "", isStreaming: true });
		const { container } = render(
			<ChatMessage
				msg={msg}
				isLast={true}
				waitingConfirm={false}
				onConfirmStep={() => {}}
			/>,
		);
		expect(container).toBeEmptyDOMElement();
	});

	it("點擊編輯會切換成 MessageEditForm，儲存並重送會呼叫 onEditUser(msg, text, true)", () => {
		const msg = makeMsg({ role: "user", content: "原始內容" });
		const onEditUser = vi.fn();
		render(
			<ChatMessage
				msg={msg}
				isLast={true}
				waitingConfirm={false}
				onConfirmStep={() => {}}
				onEditUser={onEditUser}
			/>,
		);
		fireEvent.click(screen.getByTitle("編輯"));
		const textarea = screen.getByRole("textbox");
		fireEvent.change(textarea, { target: { value: "改過的內容" } });
		fireEvent.click(screen.getByText("儲存並重送"));
		expect(onEditUser).toHaveBeenCalledWith(msg, "改過的內容", true);
	});

	it("複製按鈕會把 tool_call 區塊跟 tool_result/tool_error 標籤濾掉，但保留結果內容本身", async () => {
		const msg = makeMsg({
			content: '文字前段<|tool_call|>run_action("x")<|tool_call|><tool_result>ok</tool_result>文字後段',
		});
		const onCopy = vi.fn().mockResolvedValue(undefined);
		render(
			<ChatMessage
				msg={msg}
				isLast={true}
				waitingConfirm={false}
				onConfirmStep={() => {}}
				onCopy={onCopy}
			/>,
		);
		fireEvent.click(screen.getByTitle("複製內容"));
		await act(async () => {
			await Promise.resolve();
		});
		expect(onCopy).toHaveBeenCalledWith("文字前段ok文字後段");
	});

	it("複製時保留原始 LaTeX 分隔符（複製來源是 msg.content 本身，不是畫面顯示用的正規化字串）", async () => {
		// MarkdownBody 顯示時會把 \( \) 轉成 $ $ 給 KaTeX 用（見 normalizeMath.ts），
		// 但那個轉換只作用在渲染路徑上的一份複製字串，不會回頭改到 msg.content。
		// 複製功能是從 msg.content 取值，所以應該拿到模型原始寫的分隔符，
		// 而不是畫面上顯示的正規化版本。
		const msg = makeMsg({ content: "質量能量關係式：\\(E = mc^2\\)" });
		const onCopy = vi.fn().mockResolvedValue(undefined);
		render(
			<ChatMessage
				msg={msg}
				isLast={true}
				waitingConfirm={false}
				onConfirmStep={() => {}}
				onCopy={onCopy}
			/>,
		);
		fireEvent.click(screen.getByTitle("複製內容"));
		await act(async () => {
			await Promise.resolve();
		});
		expect(onCopy).toHaveBeenCalledWith("質量能量關係式：\\(E = mc^2\\)");
	});
});
