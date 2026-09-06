import { useCallback, useEffect, type MutableRefObject } from "react";
import type { ClientMode, ServerStatus } from "../types";

const HEALTH_CHECK_INTERVAL_MS = 15000;
const HEALTH_CHECK_TIMEOUT_MS = 2500;

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
 * local_llama：callApi("get_llm_status")
 * remote_api：優先走後端 check_remote_api（避開 webview CORS），再 fallback fetch
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
					// fallback
				}
			}
			setServerStatus({ running: false, msg: "未載入模型" });
			return;
		}

		// remote_api：先走 Python 後端，避免前端 fetch 被 CORS / 私有網路限制擋掉
		if (callApi) {
			try {
				const res = (await callApi("check_remote_api", baseUrl)) as
					| { status: string; running?: boolean; msg?: string }
					| undefined;
				if (res && typeof res.running === "boolean") {
					setServerStatus({
						running: res.running,
						msg: res.msg || (res.running ? "在線" : "離線"),
					});
					return;
				}
			} catch {
				// fallback to browser fetch
			}
		}

		try {
			const ctrl = new AbortController();
			const timer = setTimeout(() => ctrl.abort(), HEALTH_CHECK_TIMEOUT_MS);
			const root = baseUrl.replace(/\/$/, "");
			const res = await fetch(`${root}/models`, {
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
