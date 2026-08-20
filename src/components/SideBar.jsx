import {
    Bot, Cpu,
    Eraser,
    ListTree,
    PanelLeftClose, PanelLeftOpen, RefreshCw,
    Terminal,
    Trash2
} from 'lucide-react';

const MODE_OPTIONS = [
    { value: 'STEP_BY_STEP', label: '逐步確認', hint: '無視任務自己的判斷，每完成一步就暫停，等待你確認才繼續' },
    { value: 'SMART', label: '智慧確認', hint: '由模型規劃時標的「需要確認」決定：高風險步驟才暫停，其餘自動繼續' },
    { value: 'AUTO', label: '全自動', hint: '無視任務自己的判斷，中間不再暫停，直到全部完成或需要你介入' },
];

export default function Sidebar({
    isCollapsed,
    setIsCollapsed,
    baseUrl,
    setBaseUrl,
    modelName,
    setModelName,
    applyApiConfig,
    serverStatus,
    checkServerHealth,
    executionMode,
    handleModeChange,
    clearDrawings,
    clearHistory,
    showLogWindow,
    setShowLogWindow
}) {
    return (
        <aside
            className={`bg-zinc-900/60 border-r border-zinc-800 flex flex-col shrink-0 transition-all duration-300 ease-in-out relative ${isCollapsed ? 'w-16 p-3 items-center' : 'w-80 p-4'
                }`}
        >
            {/* 收合 / 展開 切換按鈕 */}
            <div className={`flex items-center justify-between w-full pb-3 border-b border-zinc-800/80 ${isCollapsed ? 'flex-col gap-3' : ''}`}>
                <div className="flex items-center gap-2 font-semibold text-zinc-100 tracking-tight overflow-hidden whitespace-nowrap">
                    <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shrink-0">
                        <Bot size={18} />
                    </div>
                    {!isCollapsed && <span>Desktop Agent</span>}
                </div>

                <button
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
                    title={isCollapsed ? "展開側邊欄" : "收合側邊欄"}
                >
                    {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
                </button>
            </div>

            {!isCollapsed ? (
                /* 展開模式內容 */
                <div className="flex-1 overflow-y-auto space-y-5 my-4 pr-1">
                    {/* LLM Server 配置卡片 */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-3 shadow-sm">
                        <div className="flex items-center justify-between text-xs font-medium text-zinc-400">
                            <span className="flex items-center gap-1.5"><Cpu size={14} /> LLM Server 配置</span>
                            <button
                                onClick={checkServerHealth}
                                className="hover:text-zinc-200 transition-colors"
                                title="重置與檢查連線"
                            >
                                <RefreshCw size={12} />
                            </button>
                        </div>

                        <div className="space-y-1">
                            <label className="text-[11px] text-zinc-400">API Base URL</label>
                            <input
                                type="text"
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono"
                            />
                        </div>

                        <div className="space-y-1">
                            <label className="text-[11px] text-zinc-400">Model Name</label>
                            <input
                                type="text"
                                value={modelName}
                                onChange={(e) => setModelName(e.target.value)}
                                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all font-mono"
                            />
                        </div>

                        <button
                            onClick={applyApiConfig}
                            className="w-full bg-zinc-100 hover:bg-white text-zinc-950 font-medium py-1.5 rounded-lg text-xs shadow transition-all active:scale-[0.98]"
                        >
                            套用連線設定
                        </button>

                        <div className="flex items-center justify-between text-xs pt-2 border-t border-zinc-800/80">
                            <span className="text-zinc-400">連線狀態</span>
                            <span className="flex items-center gap-1.5 font-medium">
                                <span className={`w-2 h-2 rounded-full ${serverStatus.running ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
                                <span className={serverStatus.running ? 'text-zinc-200' : 'text-zinc-400'}>
                                    {serverStatus.msg}
                                </span>
                            </span>
                        </div>
                    </div>

                    {/* 任務樹執行模式卡片 */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-3 shadow-sm">
                        <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
                            <ListTree size={14} /> Task Tree 執行模式
                        </div>

                        <div className="grid grid-cols-3 gap-1.5">
                            {MODE_OPTIONS.map((opt) => (
                                <button
                                    key={opt.value}
                                    onClick={() => handleModeChange(opt.value)}
                                    title={opt.hint}
                                    className={`py-2 rounded-lg text-[11px] font-medium border transition-all active:scale-[0.98] ${executionMode === opt.value
                                        ? 'bg-emerald-500 border-emerald-400 text-zinc-950'
                                        : 'bg-zinc-950 border-zinc-800 text-zinc-300 hover:bg-zinc-800'
                                        }`}
                                >
                                    {opt.label}
                                </button>
                            ))}
                        </div>
                        <p className="text-[11px] text-zinc-500 leading-relaxed">
                            {MODE_OPTIONS.find((o) => o.value === executionMode)?.hint || '每完成一步就暫停，等待你確認才繼續'}
                        </p>
                    </div>
                </div>
            ) : (
                /* 收合模式圖示選單 */
                <div className="flex-1 my-4 space-y-4 flex flex-col items-center">
                    <div
                        className={`w-3 h-3 rounded-full mt-2 ${serverStatus.running ? 'bg-emerald-500' : 'bg-rose-500'}`}
                        title={`伺服器狀態: ${serverStatus.msg}`}
                    />
                    <div
                        className="p-1.5 rounded-lg text-zinc-400"
                        title={`執行模式: ${executionMode}`}
                    >
                        <ListTree size={16} />
                    </div>
                </div>
            )}

            {/* 底部功能工具按鈕 */}
            <div className={`mt-auto space-y-2 w-full pt-2 border-t border-zinc-800/80 ${isCollapsed ? 'flex flex-col items-center' : ''}`}>
                <button
                    onClick={clearDrawings}
                    className={`flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 rounded-lg text-xs transition-all active:scale-[0.98] ${isCollapsed ? 'p-2.5 w-10' : 'w-full py-2'
                        }`}
                    title="清除螢幕標記"
                >
                    <Eraser size={14} /> {!isCollapsed && "清除螢幕標記"}
                </button>

                <button
                    onClick={clearHistory}
                    className={`flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 rounded-lg text-xs transition-all active:scale-[0.98] ${isCollapsed ? 'p-2.5 w-10' : 'w-full py-2'
                        }`}
                    title="清空對話紀錄"
                >
                    <Trash2 size={14} /> {!isCollapsed && "清空對話紀錄"}
                </button>

                <button
                    onClick={() => setShowLogWindow(!showLogWindow)}
                    className={`flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 rounded-lg text-xs transition-all active:scale-[0.98] ${isCollapsed ? 'p-2.5 w-10' : 'w-full py-2'
                        }`}
                    title="切換面板 Log"
                >
                    <Terminal size={14} /> {!isCollapsed && (showLogWindow ? '關閉面板 Log' : '開啟面板 Log')}
                </button>
            </div>
        </aside>
    );
}
