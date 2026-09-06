import { useCallback, useState } from "react";
import ChatInput from "./components/ChatInput";
import ChatMessageList from "./components/ChatMessageList";
import LogPanel from "./components/LogPanel";
import SideBar from "./components/SideBar";
import { useAgentChat } from "./hooks/useAgentChat";
import { useMessageComposer } from "./hooks/useMessageComposer";
import { usePywebview } from "./hooks/usePywebview";
import { useServerHealth } from "./hooks/useServerHealth";
import { useSidebarAutoCollapse } from "./hooks/useSidebarAutoCollapse";
import { useSidebarSettings } from "./hooks/useSidebarSettings";
import { useTheme } from "./hooks/useTheme";
import type { AgentEvent } from "./types";

export default function App() {
	const [agentBusy, setAgentBusy] = useState(false);
	const [showLog, setShowLog] = useState(false);

	const { theme, toggleTheme } = useTheme();
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
	});

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
			<SideBar
				isCollapsed={sidebarCollapsed}
				setIsCollapsed={setCollapsedByUser}
				clientMode={settings.clientMode}
				setClientMode={settings.setClientMode}
				baseUrl={settings.baseUrl}
				setBaseUrl={settings.setBaseUrl}
				apiKey={settings.apiKey}
				setApiKey={settings.setApiKey}
				modelName={settings.modelName}
				setModelName={settings.setModelName}
				modelPath={settings.modelPath}
				setModelPath={settings.setModelPath}
				applyApiConfig={() => {
					if (settings.clientMode === "local_llama") {
						callApi("load_llama_model", settings.modelPath);
					} else {
						callApi(
							"update_api_config",
							settings.baseUrl,
							settings.apiKey,
							settings.modelName,
						);
					}
				}}
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
					isBusy={agentBusy || waitingConfirm || !!waitingPermission}
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
