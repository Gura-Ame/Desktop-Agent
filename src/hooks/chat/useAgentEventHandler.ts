import { useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { AgentEvent, ChatMessage, ServerStatus } from "../../types";

function nowTs() {
	return Date.now();
}

function uid() {
	return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

type UseAgentEventHandlerArgs = {
	setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
	setLogs: Dispatch<SetStateAction<string[]>>;
	setWaitingConfirm: Dispatch<SetStateAction<boolean>>;
	setWaitingUserInput: Dispatch<SetStateAction<string | null>>;
	setServerStatus: Dispatch<SetStateAction<ServerStatus>>;
	isStreamingRef: { current: boolean };
	isBusyRef: { current: boolean };
};

export function useAgentEventHandler({
	setMessages,
	setLogs,
	setWaitingConfirm,
	setWaitingUserInput,
	setServerStatus,
	isStreamingRef,
	isBusyRef,
}: UseAgentEventHandlerArgs) {
	const handleAgentEvent = useCallback(
		(event: AgentEvent) => {
			const { type, data } = event;

			switch (type) {
				case "started":
					isBusyRef.current = true;
					break;

				case "chunk":
					isStreamingRef.current = true;
					isBusyRef.current = true;
					setMessages((prev) => {
						const last = prev[prev.length - 1];
						const chunk = typeof data === "string" ? data : String(data ?? "");
						if (last?.role === "agent" && last.isStreaming) {
							return [
								...prev.slice(0, -1),
								{ ...last, content: last.content + chunk },
							];
						}
						return [
							...prev,
							{
								id: uid(),
								role: "agent",
								content: chunk,
								isStreaming: true,
								ts: nowTs(),
							},
						];
					});
					break;

				case "chunk_patch":
					setMessages((prev) => {
						const last = prev[prev.length - 1];
						if (!last || last.role !== "agent") return prev;
						const patch = data as { old?: string; new?: string } | undefined;
						const old = patch?.old;
						const replacement = patch?.new;
						if (typeof old !== "string" || typeof replacement !== "string") return prev;

						let patched: string;
						if (last.content.endsWith(old)) {
							patched = last.content.slice(0, -old.length) + replacement;
						} else {
							const idx = last.content.lastIndexOf(old);
							if (idx >= 0) {
								patched =
								last.content.slice(0, idx) +
								replacement +
								last.content.slice(idx + old.length);
							} else {
								// 對不上就至少保證 result 進畫面（可再收成只補 tool 區段）
								console.warn("[chunk_patch] old not found", {
									lastLen: last.content.length,
									oldLen: old.length,
								});
								patched = last.content.includes("<|tool_call|>")
									? replacement
									: last.content + replacement;
							}
						}
						return [...prev.slice(0, -1), { ...last, content: patched }];
					});
					break;

				case "reset_message":
					// 後端放棄了目前這則還在串流中的內容（例如推理被截斷後改走 Planning，
					// 結果 Planning 也失敗，準備整個重新生成一次）。把這則清掉，
					// 讓接下來的 chunk 從一個乾淨的新泡泡開始，不要接在被放棄的內容後面
					// 造成「同一段話出現兩次」的錯覺。
					setMessages((prev) => {
						const last = prev[prev.length - 1];
						if (last?.role === "agent" && last.isStreaming) {
							return prev.slice(0, -1);
						}
						return prev;
					});
					break;

				case "finished":
					isStreamingRef.current = false;
					isBusyRef.current = false;
					setWaitingConfirm(false);
					setWaitingUserInput(null);
					setMessages((prev) => {
						const last = prev[prev.length - 1];
						if (last?.role === "agent") {
							return [
								...prev.slice(0, -1),
								{ ...last, isStreaming: false, ts: last.ts || nowTs() },
							];
						}
						return prev;
					});
					break;

				case "log":
					setLogs((prev) => [
						...prev,
						typeof data === "string" ? data : String(data ?? ""),
					]);
					break;

				case "server_status":
					if (data && typeof data === "object" && "running" in data) {
						setServerStatus(data as ServerStatus);
					}
					break;

				case "ask_confirm":
					isBusyRef.current = true;
					isStreamingRef.current = false;
					setWaitingConfirm(true);
					setMessages((prev) => {
						const next = [...prev];
						while (next.length > 0) {
							const last = next[next.length - 1];
							if (
								last.role === "agent" &&
								last.isStreaming &&
								!last.content?.trim()
							) {
								next.pop();
								continue;
							}
							if (last.role === "agent" && last.isStreaming) {
								next[next.length - 1] = { ...last, isStreaming: false };
							}
							break;
						}
						next.push({
							id: uid(),
							role: "agent",
							content: typeof data === "string" ? data : String(data ?? ""),
							isTree: true,
							isStreaming: false,
							ts: nowTs(),
						});
						return next;
					});
					break;

				case "waiting_input": {
					isBusyRef.current = true;
					isStreamingRef.current = false;
					const question = typeof data === "string" ? data : String(data ?? "");
					setWaitingUserInput(question);
					setMessages((prev) => {
						const next = [...prev];
						const last = next[next.length - 1];
						if (last?.role === "agent" && last.isStreaming) {
							next[next.length - 1] = { ...last, isStreaming: false };
						}
						next.push({
							id: uid(),
							role: "agent",
							content: `**❓ 需要你的協助**\n\n${question}`,
							isQuestion: true,
							ts: nowTs(),
						});
						return next;
					});
					break;
				}

				default:
					break;
			}
		},
		[
			setMessages,
			setLogs,
			setWaitingConfirm,
			setWaitingUserInput,
			setServerStatus,
			isStreamingRef,
			isBusyRef,
		],
	);

	return { handleAgentEvent };
}
