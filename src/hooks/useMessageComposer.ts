import { useCallback, useState, type MutableRefObject } from "react";
import type { ChatFile, ChatImage, ChatMessage, EditUserPayload } from "../types";

type CallApi = (method: string, ...args: unknown[]) => unknown;

type UseMessageComposerArgs = {
	callApi: CallApi;
	pinToBottom: () => void;
	setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
	waitingUserInput: string | null;
	setWaitingUserInput: (value: string | null) => void;
	setWaitingConfirm: (value: boolean) => void;
	isBusyRef: MutableRefObject<boolean>;
	isStreamingRef: MutableRefObject<boolean>;
	setAgentBusy: (value: boolean) => void;
};

/** 取檔案路徑最後一段當顯示用的檔名，同時支援 "/" 跟 "\" 兩種分隔符
 * （Windows 路徑用 "\"，但使用者也可能貼一個用 "/" 寫的路徑）。
 */
function basename(path: string): string {
	const parts = path.split(/[\\/]/);
	return parts[parts.length - 1] || path;
}

/** 把使用者附加的檔案路徑接在prompt文字後面，用清單列出來讓 agent 知道
 * 有哪些檔案可以用——這裡只傳路徑字串，不讀取、不編碼任何檔案內容
 * （本機 agent 本來就能直接用路徑存取這台機器上的檔案，見
 * main.py 的 pick_files() 開頭說明），所以沒有檔案大小限制的問題。
 */
function buildPromptWithFiles(text: string, files: ChatFile[]): string {
	if (files.length === 0) return text;
	const list = files.map((f) => `- ${f.path}`).join("\n");
	const note = `（使用者提供了以下檔案路徑，請視需要用你的工具自行讀取/處理：\n${list}）`;
	return text ? `${text}\n\n${note}` : note;
}

/**
 * 訊息輸入區的狀態與動作：輸入框文字、待送出圖片/檔案、送出/停止/複製/
 * 編輯後重送。這些全部圍繞著「使用者這一次要送什麼出去」這件事，
 * 從 App.tsx 拆出來之後，App 本身不需要再認識 compressImages、
 * user/agent 訊息物件的確切形狀這些細節。
 */
export function useMessageComposer({
	callApi,
	pinToBottom,
	setMessages,
	waitingUserInput,
	setWaitingUserInput,
	setWaitingConfirm,
	isBusyRef,
	isStreamingRef,
	setAgentBusy,
}: UseMessageComposerArgs) {
	const [input, setInput] = useState("");
	const [pendingImages, setPendingImages] = useState<ChatImage[]>([]);
	const [pendingFiles, setPendingFiles] = useState<ChatFile[]>([]);

	const addPendingImages = useCallback((list: ChatImage[]) => {
		setPendingImages((prev) => [...prev, ...list]);
	}, []);

	const removePendingImage = useCallback((id: string) => {
		setPendingImages((prev) => prev.filter((img) => img.id !== id));
	}, []);

	const removePendingFile = useCallback((id: string) => {
		setPendingFiles((prev) => prev.filter((f) => f.id !== id));
	}, []);

	/** 跳出原生檔案選擇對話框（見 main.py 的 pick_files()），選好之後只拿到
	 * 路徑字串——不讀取檔案內容，所以這裡完全不用管檔案多大。
	 */
	const pickFiles = useCallback(async () => {
		const paths = await callApi("pick_files");
		if (!Array.isArray(paths) || paths.length === 0) return;
		const list: ChatFile[] = paths.map((path) => ({
			id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
			name: basename(String(path)),
			path: String(path),
		}));
		setPendingFiles((prev) => [...prev, ...list]);
	}, [callApi]);

	const handleCopy = useCallback(async (text: string) => {
		if (!text) return;
		try {
			if (window.pywebview?.api?.copy_to_clipboard) {
				await window.pywebview.api.copy_to_clipboard(text);
				return;
			}
		} catch {
			/* fallback */
		}
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			/* ignore */
		}
	}, []);

	const handleStop = useCallback(() => {
		callApi("stop_agent");
		isBusyRef.current = false;
		isStreamingRef.current = false;
		setAgentBusy(false);
		setWaitingConfirm(false);
		setWaitingUserInput(null);
		setMessages((prev) => {
			const next = [...prev];
			const last = next[next.length - 1];
			if (last?.role === "agent" && last.isStreaming) {
				next[next.length - 1] = {
					...last,
					isStreaming: false,
					content: (last.content || "") + "\n\n*(已停止)*",
				};
			}
			return next;
		});
	}, [
		callApi,
		isBusyRef,
		isStreamingRef,
		setAgentBusy,
		setMessages,
		setWaitingConfirm,
		setWaitingUserInput,
	]);

	const handleSend = useCallback(async () => {
		const text = input.trim();
		if (!text && pendingImages.length === 0 && pendingFiles.length === 0) return;

		pinToBottom();
		const ts = Date.now();
		const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

		// 壓縮圖片，避免本地 VL GGUF 吃大圖吐 ????
		const { compressImages } = await import("../lib/imageUtils");
		const images = await compressImages(
			pendingImages.map((img) => ({
				id: img.id,
				name: img.name,
				dataUrl: img.dataUrl,
			})),
		);

		const filesForThisTurn = pendingFiles;
		const textWithFiles = buildPromptWithFiles(text, filesForThisTurn);
		const prompt =
			textWithFiles ||
			(images.length
				? "Please describe what you see in the image in detail."
				: "");
		const imageUrls = images.map((img) => img.dataUrl).filter(Boolean);

		if (waitingUserInput) {
			setMessages((prev) => [
				...prev,
				{ id, role: "user", content: text, images, ts, files: filesForThisTurn },
			]);
			callApi("submit_user_input", prompt);
			setWaitingUserInput(null);
			setInput("");
			setPendingImages([]);
			setPendingFiles([]);
			return;
		}

		isBusyRef.current = true;
		isStreamingRef.current = true;
		setAgentBusy(true);

		setMessages((prev) => [
			...prev,
			{ id, role: "user", content: text, images, ts, files: filesForThisTurn },
			{
				id: `${id}-a`,
				role: "agent",
				content: "",
				isStreaming: true,
				ts,
			},
		]);
		callApi("send_prompt", prompt, imageUrls);
		setInput("");
		setPendingImages([]);
		setPendingFiles([]);
	}, [
		input,
		pendingImages,
		pendingFiles,
		pinToBottom,
		waitingUserInput,
		setMessages,
		callApi,
		setWaitingUserInput,
		isBusyRef,
		isStreamingRef,
		setAgentBusy,
	]);

	/** user 編輯訊息後選擇「儲存並重送」：建立分枝、把新內容重新餵給 LLM。 */
	const resendEditedMessage = useCallback(
		(payload: EditUserPayload | null, fallbackText: string) => {
			pinToBottom();
			isBusyRef.current = true;
			isStreamingRef.current = true;
			setAgentBusy(true);
			const imgs = payload?.images || [];
			callApi("send_prompt", payload?.text || fallbackText, imgs);
		},
		[callApi, isBusyRef, isStreamingRef, pinToBottom, setAgentBusy],
	);

	return {
		input,
		setInput,
		pendingImages,
		addPendingImages,
		removePendingImage,
		pendingFiles,
		pickFiles,
		removePendingFile,
		handleSend,
		handleStop,
		handleCopy,
		resendEditedMessage,
	};
}
