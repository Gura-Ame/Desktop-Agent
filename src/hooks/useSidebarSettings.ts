import { useEffect, useRef, useState } from "react";
import type { ClientMode, ExecutionMode, PermissionMode } from "../types";

/**
 * 側欄裡所有「使用者偏好設定」相關的 state 集中在這裡管理——執行模式、
 * 記憶相關開關、API/本地模型連線設定。這些欄位彼此無關，但全部屬於
 * 「側欄設定」這個概念，跟聊天室訊息流、視窗版面配置是不同的關注點，
 * 原本全部攤開寫在 App.tsx 裡，光宣告就佔了快 20 行。
 *
 * 注意：這裡不含會呼叫 callApi 的 handler——那些 handler 需要
 * usePywebview 回傳的 callApi，而 usePywebview 本身又需要這裡的
 * executionModeRef，先有雞還是先有蛋的相依順序讓它們不適合放進同一個
 * hook，繼續留在 App.tsx 裡當一層很薄的 wiring。
 */
export function useSidebarSettings() {
	const [executionMode, setExecutionMode] =
		useState<ExecutionMode>("STEP_BY_STEP");
	const [forgettingEnabled, setForgettingEnabled] = useState(false);
	const [activationEnabled, setActivationEnabled] = useState(false);
	const [permissionMode, setPermissionMode] = useState<PermissionMode>("ask");
	const [clientMode, setClientMode] = useState<ClientMode>("local_llama");
	const [baseUrl, setBaseUrl] = useState("http://localhost:12356/v1");
	const [apiKey, setApiKey] = useState("lm-studio");
	const [modelName, setModelName] = useState("local-model");
	const [modelPath, setModelPath] = useState(
		String(import.meta.env.VITE_DEFAULT_MODEL_PATH ?? ""),
	);

	// usePywebview 需要隨時讀得到「目前」的執行模式（給收到事件時的 callback 用），
	// 但又不希望每次 executionMode 變動都重新訂閱事件——用 ref 讓它讀最新值即可。
	// 注意：這裡改用 useEffect 同步，不能像原本 App.tsx 那樣直接在 render 當中寫
	// `executionModeRef.current = executionMode`——那是 render 期間修改 ref 的
	// 反模式，React 19 的 eslint-plugin-react-hooks（react-hooks/refs）跟
	// React Compiler 都會直接判定為錯誤，因為 render 理論上可能被中斷重跑、
	// 也可能被拿去做非同步的 concurrent 渲染，這種「順便」的 side effect
	// 不該混在 render 本體裡。
	const executionModeRef = useRef(executionMode);
	useEffect(() => {
		executionModeRef.current = executionMode;
	}, [executionMode]);

	return {
		executionMode,
		setExecutionMode,
		executionModeRef,
		forgettingEnabled,
		setForgettingEnabled,
		activationEnabled,
		setActivationEnabled,
		permissionMode,
		setPermissionMode,
		clientMode,
		setClientMode,
		baseUrl,
		setBaseUrl,
		apiKey,
		setApiKey,
		modelName,
		setModelName,
		modelPath,
		setModelPath,
	};
}
