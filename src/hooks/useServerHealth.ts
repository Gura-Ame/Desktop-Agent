import { useCallback, useEffect, type MutableRefObject } from "react";
import type { ClientMode, ServerStatus } from "../types";

const HEALTH_CHECK_INTERVAL_MS = 15000;
const HEALTH_CHECK_TIMEOUT_MS = 1500;

type UseServerHealthArgs = {
	clientMode: ClientMode;
	baseUrl: string;
	isBusyRef: MutableRefObject<boolean>;
	isStreamingRef: MutableRefObject<boolean>;
	setServerStatus: (status: ServerStatus) => void;
	callApi?: (method: string, ...args: unknown[]) => unknown;
};

/**
 * 檢查 LLM 伺服器狀態，並每 15 秒輪詢一次。
 * local_llama 模式下不走 HTTP，而是透過 callApi("get_llm_status") 檢查本機模型是否已真正載入。
 * 啟動且未載入模型時如實顯示「未載入模型」（紅燈），載入成功後才顯示「已載入 (模型名)」（綠燈）。
 * 嚴禁在 agent / 串流工作中對 server 發請求，否則可能把本地 llama 打掛——
 * 這正是 isBusyRef / isStreamingRef 存在的原因。
 *
 * 從 App.tsx 拆出來：這塊輪詢邏輯不需要知道聊天室其他任何狀態，
 * 只需要 clientMode/baseUrl/callApi 當輸入、setServerStatus 當輸出。
 */
export function useServerHealth({
	clientMode,
	baseUrl,
	isBusyRef,
	isStreamingRef,
	setServerStatus,
	callApi,
}: UseServerHealthArgs) {
	const checkServerHealth = useCallback(async () => {
		if (isBusyRef.current || isStreamingRef.current) return;

		if (clientMode === "local_llama") {
			if (callApi) {
				try {
					const res = (await callApi("get_llm_status")) as
						| {
								status: string;
								is_llama: boolean;
								model_loaded: boolean;
								model_name?: string;
						  }
						| undefined;
					if (res && res.model_loaded) {
						setServerStatus({
							running: true,
							msg: res.model_name ? `已載入 (${res.model_name})` : "已載入模型",
						});
						return;
					}
				} catch {
					// fallback to offline/unloaded
				}
			}
			setServerStatus({ running: false, msg: "未載入模型" });
			return;
		}

		try {
			const ctrl = new AbortController();
			const timer = setTimeout(() => ctrl.abort(), HEALTH_CHECK_TIMEOUT_MS);
			const res = await fetch(`${baseUrl.replace(/\/$/, "")}/models`, {
				method: "GET",
				signal: ctrl.signal,
			});
			clearTimeout(timer);
			if (res.ok) {
				setServerStatus({ running: true, msg: "在線" });
			} else {
				setServerStatus({ running: false, msg: `異常 (${res.status})` });
			}
		} catch {
			if (!isBusyRef.current && !isStreamingRef.current) {
				setServerStatus({ running: false, msg: "離線" });
			}
		}
	}, [clientMode, baseUrl, isBusyRef, isStreamingRef, setServerStatus, callApi]);

	useEffect(() => {
		checkServerHealth();
		const id = setInterval(checkServerHealth, HEALTH_CHECK_INTERVAL_MS);
		return () => clearInterval(id);
	}, [checkServerHealth]);

	return { checkServerHealth };
}
