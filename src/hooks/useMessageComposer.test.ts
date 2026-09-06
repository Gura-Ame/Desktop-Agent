import { act, renderHook } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../types";
import { useMessageComposer } from "./useMessageComposer";

function setup() {
	const callApi = vi.fn();
	const pinToBottom = vi.fn();
	const setWaitingConfirm = vi.fn();

	const hook = renderHook(() => {
		const [messages, setMessages] = useState<ChatMessage[]>([]);
		const [waitingUserInput, setWaitingUserInput] = useState<string | null>(
			null,
		);
		const isBusyRef = useRef(false);
		const isStreamingRef = useRef(false);
		const [agentBusy, setAgentBusy] = useState(false);

		const composer = useMessageComposer({
			callApi,
			pinToBottom,
			setMessages,
			waitingUserInput,
			setWaitingUserInput,
			setWaitingConfirm,
			isBusyRef,
			isStreamingRef,
			setAgentBusy,
		});

		return {
			...composer,
			messages,
			waitingUserInput,
			setWaitingUserInput,
			isBusyRef,
			isStreamingRef,
			agentBusy,
		};
	});

	return { ...hook, callApi, pinToBottom, setWaitingConfirm };
}

describe("useMessageComposer", () => {
	it("輸入跟圖片都是空的時候，送出不會做任何事", async () => {
		const { result, callApi } = setup();
		await act(async () => {
			await result.current.handleSend();
		});
		expect(callApi).not.toHaveBeenCalled();
		expect(result.current.messages).toHaveLength(0);
	});

	it("一般送出：推進 user + agent(streaming) 兩則訊息，並呼叫 send_prompt", async () => {
		const { result, callApi, pinToBottom } = setup();
		act(() => {
			result.current.setInput("你好");
		});
		await act(async () => {
			await result.current.handleSend();
		});

		expect(pinToBottom).toHaveBeenCalled();
		expect(result.current.messages).toHaveLength(2);
		expect(result.current.messages[0]).toMatchObject({
			role: "user",
			content: "你好",
		});
		expect(result.current.messages[1]).toMatchObject({
			role: "agent",
			content: "",
			isStreaming: true,
		});
		expect(callApi).toHaveBeenCalledWith("send_prompt", "你好", []);
		expect(result.current.isBusyRef.current).toBe(true);
		expect(result.current.isStreamingRef.current).toBe(true);
		// 送出後應該清空輸入框
		expect(result.current.input).toBe("");
	});

	it("waitingUserInput 有值時，送出只推進 user 訊息並呼叫 submit_user_input（不建立新的 agent placeholder）", async () => {
		const { result, callApi } = setup();
		act(() => {
			result.current.setWaitingUserInput("請問要搜尋什麼？");
			result.current.setInput("87");
		});
		await act(async () => {
			await result.current.handleSend();
		});

		expect(result.current.messages).toHaveLength(1);
		expect(result.current.messages[0]).toMatchObject({
			role: "user",
			content: "87",
		});
		expect(callApi).toHaveBeenCalledWith("submit_user_input", "87");
		expect(callApi).not.toHaveBeenCalledWith(
			"send_prompt",
			expect.anything(),
			expect.anything(),
		);
		expect(result.current.waitingUserInput).toBeNull();
	});

	it("handleStop 會呼叫 stop_agent、重置忙碌狀態，並在最後一則 streaming 訊息補上「已停止」", async () => {
		const { result, callApi, setWaitingConfirm } = setup();
		act(() => {
			result.current.setInput("你好");
		});
		await act(async () => {
			await result.current.handleSend();
		});

		act(() => {
			result.current.handleStop();
		});

		expect(callApi).toHaveBeenCalledWith("stop_agent");
		expect(result.current.isBusyRef.current).toBe(false);
		expect(result.current.isStreamingRef.current).toBe(false);
		expect(setWaitingConfirm).toHaveBeenCalledWith(false);
		expect(result.current.waitingUserInput).toBeNull();
		const lastMsg = result.current.messages[result.current.messages.length - 1];
		expect(lastMsg.isStreaming).toBe(false);
		expect(lastMsg.content).toContain("已停止");
	});

	it("resendEditedMessage 會用 payload 裡的文字/圖片呼叫 send_prompt，沒有 payload 時退回原始文字", () => {
		const { result, callApi, pinToBottom } = setup();

		act(() => {
			result.current.resendEditedMessage(
				{ text: "改過的內容", images: ["data:img1"] },
				"原始內容",
			);
		});
		expect(pinToBottom).toHaveBeenCalled();
		expect(callApi).toHaveBeenCalledWith("send_prompt", "改過的內容", [
			"data:img1",
		]);

		act(() => {
			result.current.resendEditedMessage(null, "原始內容");
		});
		expect(callApi).toHaveBeenCalledWith("send_prompt", "原始內容", []);
	});

	it("pickFiles 呼叫 pick_files 並把回傳的路徑轉成 pendingFiles（用路徑最後一段當顯示檔名）", async () => {
		const { result, callApi } = setup();
		callApi.mockResolvedValueOnce([
			"C:\\Users\\me\\Desktop\\report.pdf",
			"/home/me/notes.txt",
		]);

		await act(async () => {
			await result.current.pickFiles();
		});

		expect(callApi).toHaveBeenCalledWith("pick_files");
		expect(result.current.pendingFiles).toHaveLength(2);
		expect(result.current.pendingFiles[0]).toMatchObject({
			name: "report.pdf",
			path: "C:\\Users\\me\\Desktop\\report.pdf",
		});
		expect(result.current.pendingFiles[1]).toMatchObject({
			name: "notes.txt",
			path: "/home/me/notes.txt",
		});
	});

	it("pickFiles 使用者取消選擇（回傳空陣列）時不會新增任何 pendingFiles", async () => {
		const { result, callApi } = setup();
		callApi.mockResolvedValueOnce([]);
		await act(async () => {
			await result.current.pickFiles();
		});
		expect(result.current.pendingFiles).toHaveLength(0);
	});

	it("removePendingFile 會把指定的檔案從 pendingFiles 移除", async () => {
		const { result, callApi } = setup();
		callApi.mockResolvedValueOnce(["/a/b/one.txt", "/a/b/two.txt"]);
		await act(async () => {
			await result.current.pickFiles();
		});
		const idToRemove = result.current.pendingFiles[0].id;
		act(() => {
			result.current.removePendingFile(idToRemove);
		});
		expect(result.current.pendingFiles).toHaveLength(1);
		expect(result.current.pendingFiles[0].name).toBe("two.txt");
	});

	it("送出時會把附加的檔案路徑清單接在 prompt 文字後面，並且不影響顯示用的 content", async () => {
		const { result, callApi } = setup();
		callApi.mockResolvedValueOnce(["/a/b/report.pdf"]);
		await act(async () => {
			await result.current.pickFiles();
		});

		act(() => {
			result.current.setInput("幫我看看這份報告");
		});
		await act(async () => {
			await result.current.handleSend();
		});

		// 聊天氣泡顯示的 content 應該保持使用者原始輸入，不要把路徑雜訊也顯示進去
		expect(result.current.messages[0].content).toBe("幫我看看這份報告");
		expect(result.current.messages[0].files).toEqual([
			expect.objectContaining({ path: "/a/b/report.pdf", name: "report.pdf" }),
		]);
		// 但實際送給 agent 的 prompt 字串要包含路徑，agent 才知道有這個檔案可以用
		const sendCall = callApi.mock.calls.find((c) => c[0] === "send_prompt");
		expect(sendCall?.[1]).toContain("/a/b/report.pdf");
		expect(sendCall?.[1]).toContain("幫我看看這份報告");
		// 送出後應該清空待送出的檔案
		expect(result.current.pendingFiles).toHaveLength(0);
	});

	it("只附加檔案、沒有輸入文字時，prompt 仍然會包含檔案路徑說明", async () => {
		const { result, callApi } = setup();
		callApi.mockResolvedValueOnce(["/a/b/data.csv"]);
		await act(async () => {
			await result.current.pickFiles();
		});
		await act(async () => {
			await result.current.handleSend();
		});
		const sendCall = callApi.mock.calls.find((c) => c[0] === "send_prompt");
		expect(sendCall?.[1]).toContain("/a/b/data.csv");
	});
});
