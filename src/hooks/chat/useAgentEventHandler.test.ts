import { act, renderHook } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";
import type {
	AgentEvent,
	ChatMessage,
	PermissionInfo,
	ServerStatus,
} from "../../types";
import { useAgentEventHandler } from "./useAgentEventHandler";

// 這個 hook 是「後端內部路由標記(<|direct|>/<|plan|>)不該外露到聊天畫面」
// 這個修復實際依賴的前端機制：Python 那邊用 chunk_patch 事後補一次差異，
// 這裡驗證 chunk_patch 真的能把畫面上的標記換掉，而不會誤刪/誤留內容。
function setup() {
	return renderHook(() => {
		const [messages, setMessages] = useState<ChatMessage[]>([]);
		const [logs, setLogs] = useState<string[]>([]);
		const [waitingConfirm, setWaitingConfirm] = useState(false);
		const [waitingUserInput, setWaitingUserInput] = useState<string | null>(
			null,
		);
		const [waitingPermission, setWaitingPermission] =
			useState<PermissionInfo | null>(null);
		const [, setServerStatus] = useState<ServerStatus>({
			running: false,
			msg: "",
		});
		const isStreamingRef = useRef(false);
		const isBusyRef = useRef(false);

		const { handleAgentEvent } = useAgentEventHandler({
			setMessages,
			setLogs,
			setWaitingConfirm,
			setWaitingUserInput,
			setWaitingPermission,
			setServerStatus,
			isStreamingRef,
			isBusyRef,
		});

		return {
			handleAgentEvent,
			messages,
			logs,
			waitingConfirm,
			waitingUserInput,
			waitingPermission,
		};
	});
}

describe("useAgentEventHandler", () => {
	it("chunk 事件會累積內容到最新一則 streaming 的 agent 訊息", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "chunk",
				data: "<|direct|>\n",
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk",
				data: "哈囉",
			} as AgentEvent);
		});
		expect(result.current.messages).toHaveLength(1);
		expect(result.current.messages[0].content).toBe("<|direct|>\n哈囉");
	});

	it("chunk_patch 可以把畫面上的內部路由標記換掉，不影響其餘文字", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "chunk",
				data: '<|direct|>\n<|tool_call|>open_chrome_incognito(query="")<|tool_call|>',
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk_patch",
				data: { old: "<|direct|>\n", new: "" },
			} as AgentEvent);
		});
		expect(result.current.messages[0].content).toBe(
			'<|tool_call|>open_chrome_incognito(query="")<|tool_call|>',
		);
	});

	it("<|plan|> 標記被拿掉時，後面接著的一句話原因說明要保留（不能整段被清空）", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "chunk",
				data: "<|plan|>需要先確認搜尋關鍵字才能繼續",
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk_patch",
				data: { old: "<|plan|>", new: "" },
			} as AgentEvent);
		});
		expect(result.current.messages[0].content).toBe("需要先確認搜尋關鍵字才能繼續");
	});

	it("同一個標記字串在同一則訊息裡重複出現多次時，chunk_patch 只換掉最後一次新出現的那個", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "chunk",
				data: '<|direct|>\n<|tool_call|>run_action("A")<|tool_call|>',
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk_patch",
				data: { old: "<|direct|>\n", new: "" },
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk",
				data: '<|direct|>\n<|tool_call|>run_action("B")<|tool_call|>',
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk_patch",
				data: { old: "<|direct|>\n", new: "" },
			} as AgentEvent);
		});
		expect(result.current.messages[0].content).toBe(
			'<|tool_call|>run_action("A")<|tool_call|><|tool_call|>run_action("B")<|tool_call|>',
		);
	});

	it("reset_message 會丟掉目前還在 streaming 的訊息，讓下一個 chunk 開新泡泡", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "chunk",
				data: "被放棄的草稿",
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "reset_message",
				data: null,
			} as AgentEvent);
			result.current.handleAgentEvent({
				type: "chunk",
				data: "全新的回覆",
			} as AgentEvent);
		});
		expect(result.current.messages).toHaveLength(1);
		expect(result.current.messages[0].content).toBe("全新的回覆");
	});

	it("waiting_input 會把問題內容顯示成獨立的 agent 訊息", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "waiting_input",
				data: "請問要搜尋什麼關鍵字？",
			} as AgentEvent);
		});
		expect(result.current.waitingUserInput).toBe("請問要搜尋什麼關鍵字？");
		const last = result.current.messages[result.current.messages.length - 1];
		expect(last.content).toContain("請問要搜尋什麼關鍵字？");
		expect(last.isQuestion).toBe(true);
	});

	it("permission_request 會設定 waitingPermission 並推進一則帶 permissionInfo 的訊息", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "permission_request",
				data: { tool: "execute_python", args: "'print(1)'", risk: "dangerous" },
			} as AgentEvent);
		});
		expect(result.current.waitingPermission).toEqual({
			tool: "execute_python",
			args: "'print(1)'",
			risk: "dangerous",
		});
		const last = result.current.messages[result.current.messages.length - 1];
		expect(last.isPermissionRequest).toBe(true);
		expect(last.permissionInfo?.tool).toBe("execute_python");
	});

	it("finished 事件會清掉 waitingPermission", () => {
		const { result } = setup();
		act(() => {
			result.current.handleAgentEvent({
				type: "permission_request",
				data: { tool: "click_mouse", args: "", risk: "dangerous" },
			} as AgentEvent);
		});
		expect(result.current.waitingPermission).not.toBeNull();
		act(() => {
			result.current.handleAgentEvent({ type: "finished" } as AgentEvent);
		});
		expect(result.current.waitingPermission).toBeNull();
	});
});
