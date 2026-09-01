import {
	BrainCog,
	Bot,
	ListTree,
	Moon,
	PanelLeftClose,
	PanelLeftOpen,
	Sun,
	Zap,
} from "lucide-react";
import type { ClientMode, ExecutionMode, ServerStatus, Theme } from "../types";
import ExecutionModeCard from "./sidebar/ExecutionModeCard";
import LlmClientCard from "./sidebar/LlmClientCard";
import SidebarFooterActions from "./sidebar/SidebarFooterActions";
import ToggleFeatureCard from "./sidebar/ToggleFeatureCard";

type SidebarProps = {
	isCollapsed: boolean;
	setIsCollapsed: (collapsed: boolean) => void;
	clientMode: ClientMode;
	setClientMode: (mode: ClientMode) => void;
	baseUrl: string;
	setBaseUrl: (url: string) => void;
	apiKey: string;
	setApiKey: (key: string) => void;
	modelName: string;
	setModelName: (name: string) => void;
	modelPath: string;
	setModelPath: (path: string) => void;
	applyApiConfig: () => void;
	serverStatus: ServerStatus;
	checkServerHealth: () => void;
	executionMode: ExecutionMode;
	handleModeChange: (mode: ExecutionMode) => void;
	clearDrawings: () => void;
	clearHistory: () => void;
	showLogWindow: boolean;
	setShowLogWindow: (show: boolean) => void;
	forgettingEnabled: boolean;
	handleForgettingToggle: (enabled: boolean) => void;
	activationEnabled: boolean;
	handleActivationToggle: (enabled: boolean) => void;
	theme?: Theme;
	toggleTheme?: () => void;
};

export default function Sidebar({
	isCollapsed,
	setIsCollapsed,
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
	applyApiConfig,
	serverStatus,
	checkServerHealth,
	executionMode,
	handleModeChange,
	clearDrawings,
	clearHistory,
	showLogWindow,
	setShowLogWindow,
	forgettingEnabled,
	handleForgettingToggle,
	activationEnabled,
	handleActivationToggle,
	theme,
	toggleTheme,
}: SidebarProps) {
	return (
		<aside
			className={`bg-zinc-900/60 border-r border-zinc-800 flex flex-col shrink-0 transition-all duration-300 ease-in-out relative ${
				isCollapsed ? "w-16 p-3 items-center" : "w-80 p-4"
			}`}
		>
			{/* 收合 / 展開 切換按鈕 */}
			<div
				className={`flex items-center justify-between w-full pb-3 border-b border-zinc-800/80 ${isCollapsed ? "flex-col gap-3" : ""}`}
			>
				<div className="flex items-center gap-2 font-semibold text-zinc-100 tracking-tight overflow-hidden whitespace-nowrap">
					<div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
						<Bot size={18} />
					</div>
					{!isCollapsed && <span>Desktop Agent</span>}
				</div>

				<div className={`flex items-center gap-0.5 ${isCollapsed ? "flex-col" : ""}`}>
					{toggleTheme && (
						<button
							type="button"
							onClick={toggleTheme}
							className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
							title={theme === "dark" ? "切換淺色" : "切換深色"}
						>
							{theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
						</button>
					)}
					<button
						type="button"
						onClick={() => setIsCollapsed(!isCollapsed)}
						className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
						title={isCollapsed ? "展開側邊欄" : "收合側邊欄"}
					>
						{isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
					</button>
				</div>
			</div>

			{!isCollapsed ? (
				/* 展開模式內容 */
				<div className="flex-1 overflow-y-auto space-y-5 my-4 pr-1">
					<LlmClientCard
						clientMode={clientMode}
						setClientMode={setClientMode}
						baseUrl={baseUrl}
						setBaseUrl={setBaseUrl}
						apiKey={apiKey}
						setApiKey={setApiKey}
						modelName={modelName}
						setModelName={setModelName}
						modelPath={modelPath}
						setModelPath={setModelPath}
						applyApiConfig={applyApiConfig}
						serverStatus={serverStatus}
						checkServerHealth={checkServerHealth}
					/>

					<ExecutionModeCard
						executionMode={executionMode}
						handleModeChange={handleModeChange}
					/>

					<ToggleFeatureCard
						icon={<BrainCog size={14} />}
						label="漸進式遺忘"
						enabled={forgettingEnabled}
						onToggle={handleForgettingToggle}
						enabledDescription="開啟中：長期沒被存取的記憶會自動降低解析度（先回收局部覆寫，很久之後再精煉成更抽象的摘要），不會直接刪除。"
						disabledDescription="關閉中：所有長期記憶維持原本的細節，不會自動被降低解析度。"
					/>

					<ToggleFeatureCard
						icon={<Zap size={14} />}
						label="Activation（跨對話記憶啟用度）"
						enabled={activationEnabled}
						onToggle={handleActivationToggle}
						enabledDescription="開啟中：記憶被想起（recall / search）的次數與新鮮度會跨對話累積成分數，之後排序時常被想起的東西會更優先被看到（會隨時間慢慢衰減，不是永久加分）。"
						disabledDescription="關閉中：所有記憶單純依照關聯度與最近使用時間排序，不會有額外的「常被想起」加權。"
					/>
				</div>
			) : (
				/* 收合模式圖示選單 */
				<div className="flex-1 my-4 space-y-4 flex flex-col items-center">
					<div
						className={`w-3 h-3 rounded-full mt-2 ${serverStatus.running ? "bg-emerald-500" : "bg-rose-500"}`}
						title={`狀態: ${serverStatus.msg}`}
					/>
					<div className="p-1.5 rounded-lg text-zinc-400" title={`執行模式: ${executionMode}`}>
						<ListTree size={16} />
					</div>
				</div>
			)}

			<SidebarFooterActions
				isCollapsed={isCollapsed}
				clearDrawings={clearDrawings}
				clearHistory={clearHistory}
				showLogWindow={showLogWindow}
				setShowLogWindow={setShowLogWindow}
			/>
		</aside>
	);
}
