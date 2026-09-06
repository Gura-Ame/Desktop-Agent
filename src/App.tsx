import { useCallback, useState } from "react";
import ChatInput from "./components/ChatInput";
import ChatMessageList from "./components/ChatMessageList";
import LogPanel from "./components/LogPanel";
import SideBar from "./components/SideBar";
import { ToastHost } from "./components/ui/Toast";
import { useAgentChat } from "./hooks/useAgentChat";
import { useMessageComposer } from "./hooks/useMessageComposer";
import { usePywebview } from "./hooks/usePywebview";
import { useServerHealth } from "./hooks/useServerHealth";
import { useSidebarAutoCollapse } from "./hooks/useSidebarAutoCollapse";
import { useSidebarSettings } from "./hooks/useSidebarSettings";
import { useTheme } from "./hooks/useTheme";
import { useToast } from "./hooks/useToast";
import type { AgentEvent } from "./types";

export default function App() {
	const [agentBusy, setAgentBusy] = useState(false);
	const [showLog, setShowLog] = useState(false);

	const { theme, toggleTheme } = useTheme();
	const { toasts, pushToast, dismissToast } = useToast();
	const { collapsed: sidebarCollapsed, setCollapsedByUser } =
		useSidebarAutoCollapse();
	const settings = useSidebarSettings();

	const {
		messages,
		setMessages,
		logs,
		serverStatus,
		setServerStatus,
		waitingConfirm,
		setWaitingConfirm,
		waitingUserInput,
		setWaitingUserInput,
		waitingPermission,
		resolvePermissionMessage,
		chatEndRef,
		scrollContainerRef,
		handleScroll,
		pinToBottom,
		isStreamingRef,
		isBusyRef,
		handleAgentEvent,
		clearMessages,
		editUserMessage,
		switchFork,
	} = useAgentChat();

	const onAgentEvent = useCallback(
		(event: AgentEvent) => {
			handleAgentEvent(event);
			if (event?.type === "finished" || event?.type === "ask_confirm") {
				// ask_confirm 仍算等待中；finished 才真正結束
				if (event.type === "finished") setAgentBusy(false);
			}
			if (event?.type === "started" || event?.type === "chunk") {
				setAgentBusy(true);
			}
		},
		[handleAgentEvent],
	);

	const { callApi } = usePywebview({
		onEvent: onAgentEvent,
		executionModeRef: settings.executionModeRef,
	});

	const { checkServerHealth } = useServerHealth({
		clientMode: settings.clientMode,
		baseUrl: settings.baseUrl,
		isBusyRef,
		isStreamingRef,
		setServerStatus,
		callApi,
	});

	const [isModelLoading, setIsModelLoading] = useState(false);
	const [loadMessage, setLoadMessage] = useState<{
		type: "success" | "error" | "info";
		text: string;
	} | null>(null);

	const handlePickModelFile = async () => {
		try {
			const picked = (await callApi("pick_model_file")) as string | undefined;
			if (picked && typeof picked === "string" && picked.trim()) {
				settings.setModelPath(picked.trim());
				settings.addRecentModel(picked.trim());
			}
		} catch (e) {
			console.error("pick_model_file error:", e);
		}
	};

	const handleApplyApiConfig = async () => {
		if (settings.clientMode === "local_llama") {
			if (!settings.modelPath || !settings.modelPath.trim()) {
				pushToast("error", "請先指定或選取 GGUF 模型檔案路徑");
				return;
			}
			setIsModelLoading(true);
			setLoadMessage(null);
			try {
				const res = (await callApi("load_llama_model", settings.modelPath.trim())) as
					| { status: string; model_name?: string; msg?: string }
					| undefined;
				if (res?.status === "ok") {
					settings.addRecentModel(settings.modelPath.trim());
					const name = res.model_name || "已就緒";
					pushToast("success", `模型載入成功！(${name})`);
					await checkServerHealth();
				} else {
					pushToast("error", `載入失敗: ${res?.msg || "未能初始化模型"}`);
					await checkServerHealth();
				}
			} catch (e) {
				pushToast(
					"error",
					`載入失敗: ${e instanceof Error ? e.message : String(e)}`,
				);
				await checkServerHealth();
			} finally {
				setIsModelLoading(false);
			}
		} else {
			setLoadMessage(null);
			try {
				await callApi(
					"update_api_config",
					settings.baseUrl,
					settings.apiKey,
					settings.modelName,
				);
				await checkServerHealth();
				pushToast("success", "已套用 Remote API 連線設定");
			} catch (e) {
				pushToast(
					"error",
					`套用失敗: ${e instanceof Error ? e.message : String(e)}`,
				);
			}
		}
	};

	const {
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
	} = useMessageComposer({
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

	return (
		<div className="flex h-screen w-screen overflow-hidden bg-[#e8e8ea] font-sans text-sm text-zinc-900 antialiased dark:bg-[#1c1c1e] dark:text-zinc-100">
			<ToastHost toasts={toasts} onDismiss={dismissToast} />
			<SideBar
				isCollapsed={sidebarCollapsed}
				setIsCollapsed={setCollapsedByUser}
				clientMode={settings.clientMode}
				setClientMode={(mode) => {
					settings.setClientMode(mode);
					// 切換模式時先標示檢查中，避免沿用上一模式的綠/紅燈造成誤解
					setServerStatus({ running: false, msg: "檢查中…" });
				}}
				baseUrl={settings.baseUrl}
				setBaseUrl={settings.setBaseUrl}
				apiKey={settings.apiKey}
				setApiKey={settings.setApiKey}
				modelName={settings.modelName}
				setModelName={settings.setModelName}
				modelPath={settings.modelPath}
				setModelPath={settings.setModelPath}
				applyApiConfig={handleApplyApiConfig}
				recentModels={settings.recentModels}
				onPickModelFile={handlePickModelFile}
				isModelLoading={isModelLoading}
				loadMessage={loadMessage}
				onClearRecentModels={settings.clearRecentModels}
				serverStatus={serverStatus}
				checkServerHealth={checkServerHealth}
				executionMode={settings.executionMode}
				handleModeChange={(mode) => {
					settings.setExecutionMode(mode);
					callApi("set_execution_mode", mode);
				}}
				forgettingEnabled={settings.forgettingEnabled}
				handleForgettingToggle={(enabled) => {
					settings.setForgettingEnabled(enabled);
					callApi("set_forgetting_enabled", enabled);
				}}
				activationEnabled={settings.activationEnabled}
				handleActivationToggle={(enabled) => {
					settings.setActivationEnabled(enabled);
					callApi("set_activation_enabled", enabled);
				}}
				permissionMode={settings.permissionMode}
				handlePermissionModeChange={(mode) => {
					settings.setPermissionMode(mode);
					callApi("set_permission_mode", mode);
				}}
				clearDrawings={() => callApi("clear_drawings")}
				clearHistory={() => {
					clearMessages();
					callApi("clear_history");
				}}
				preloadVisionModels={async () => {
					pushToast("info", "正在背景預載視覺模型…");
					try {
						const res = (await callApi("preload_vision_models")) as
							| { status?: string; msg?: string }
							| undefined;
						pushToast(
							"success",
							res?.msg || "已開始預載，完成後可即時分析圖片",
						);
					} catch (e) {
						pushToast(
							"error",
							`預載失敗：${e instanceof Error ? e.message : String(e)}`,
						);
						throw e;
					}
				}}
				unloadVisionModels={async () => {
					pushToast("info", "正在釋放視覺模型顯存…");
					try {
						const res = (await callApi("unload_vision_models")) as
							| { status?: string; msg?: string }
							| undefined;
						pushToast("success", res?.msg || "視覺模型顯存已釋放");
					} catch (e) {
						pushToast(
							"error",
							`釋放失敗：${e instanceof Error ? e.message : String(e)}`,
						);
						throw e;
					}
				}}
				showLogWindow={showLog}
				setShowLogWindow={setShowLog}
				theme={theme}
				toggleTheme={toggleTheme}
			/>

			<main className="relative flex min-w-0 flex-1 flex-col bg-[#e8e8ea] dark:bg-[#1c1c1e]">
				<ChatMessageList
					messages={messages}
					waitingConfirm={waitingConfirm}
					onConfirmStep={() => {
						setWaitingConfirm(false);
						setAgentBusy(true);
						isBusyRef.current = true;
						callApi("confirm_step");
					}}
					onCopy={handleCopy}
					onSwitchFork={switchFork}
					onEditUser={(m, nextText, resend) => {
						if (!resend) {
							editUserMessage(m, nextText, false);
							return;
						}
						// 建立分枝 + 重新餵給 LLM（含原圖）
						const payload = editUserMessage(m, nextText, true);
						resendEditedMessage(payload, nextText);
					}}
					onRespondPermission={(msgId, decision) => {
						resolvePermissionMessage(msgId, decision);
						callApi("respond_permission", decision);
					}}
					scrollContainerRef={scrollContainerRef}
					chatEndRef={chatEndRef}
					onScroll={handleScroll}
				/>

				<ChatInput
					value={input}
					onChange={setInput}
					onSend={handleSend}
					onStop={handleStop}
					waitingUserInput={waitingUserInput}
					isBusy={agentBusy || !!waitingPermission}
					images={pendingImages}
					onAddImages={addPendingImages}
					onRemoveImage={removePendingImage}
					files={pendingFiles}
					onPickFiles={pickFiles}
					onRemoveFile={removePendingFile}
				/>
			</main>

			{showLog && <LogPanel logs={logs} onClose={() => setShowLog(false)} />}
		</div>
	);
}
