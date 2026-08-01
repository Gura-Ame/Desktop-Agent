import { useCallback, useEffect, useRef, useState } from 'react';
import ChatInput from './components/ChatInput';
import ChatMessage from './components/ChatMessage';
import LogPanel from './components/LogPanel';
import SideBar from './components/SideBar';
import { useAgentChat } from './hooks/useAgentChat';
import { usePywebview } from './hooks/usePywebview';
import { useTheme } from './hooks/useTheme';

/** 視窗寬度低於此值時自動收合側欄 */
const SIDEBAR_AUTO_COLLAPSE_PX = 900;

export default function App() {
  const [input, setInput] = useState('');
  const [showLog, setShowLog] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX,
  );
  const [executionMode, setExecutionMode] = useState('STEP_BY_STEP');
  const [baseUrl, setBaseUrl] = useState('http://localhost:12356/v1');
  const [modelName, setModelName] = useState('local-model');

  const executionModeRef = useRef(executionMode);
  executionModeRef.current = executionMode;

  // 使用者手動收合時記住，放大視窗後不要擅自展開
  const userPreferCollapsedRef = useRef(false);
  // 是否因視窗過窄而自動收合（放大後可自動展開，除非使用者偏好收合）
  const autoCollapsedRef = useRef(
    typeof window !== 'undefined' && window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX,
  );

  const { theme, toggleTheme } = useTheme();

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
    chatEndRef,
    scrollContainerRef,
    handleScroll,
    pinToBottom,
    isStreamingRef,
    isBusyRef,
    handleAgentEvent,
    clearMessages,
  } = useAgentChat();

  const { callApi } = usePywebview({
    onEvent: handleAgentEvent,
    executionModeRef,
  });

  // 小視窗自動收合側欄
  useEffect(() => {
    const onResize = () => {
      const narrow = window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX;
      if (narrow) {
        autoCollapsedRef.current = true;
        setSidebarCollapsed(true);
      } else if (autoCollapsedRef.current && !userPreferCollapsedRef.current) {
        autoCollapsedRef.current = false;
        setSidebarCollapsed(false);
      }
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const handleSidebarCollapse = useCallback((collapsed) => {
    userPreferCollapsedRef.current = collapsed;
    autoCollapsedRef.current = false;
    setSidebarCollapsed(collapsed);
  }, []);

  /**
   * 檢查 LLM 伺服器狀態。
   * 嚴禁在 agent / 串流工作中對 server 發請求，否則可能把本地 llama 打掛。
   */
  const checkServerHealth = useCallback(async () => {
    if (isBusyRef.current || isStreamingRef.current) {
      return;
    }
    try {
      // 僅做極輕量探測；timeout 短，避免卡住 UI
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 1500);
      const res = await fetch(`${baseUrl.replace(/\/$/, '')}/models`, {
        method: 'GET',
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (res.ok) {
        setServerStatus({ running: true, msg: '在線' });
      } else {
        setServerStatus({ running: false, msg: `異常 (${res.status})` });
      }
    } catch {
      // 工作中被略過、或離線
      if (!isBusyRef.current && !isStreamingRef.current) {
        setServerStatus({ running: false, msg: '離線' });
      }
    }
  }, [baseUrl, isBusyRef, isStreamingRef, setServerStatus]);

  useEffect(() => {
    checkServerHealth();
    const id = setInterval(checkServerHealth, 15000);
    return () => clearInterval(id);
  }, [checkServerHealth]);

  const handleCopy = useCallback(
    async (text) => {
      if (!text) return;
      try {
        if (window.pywebview?.api?.copy_to_clipboard) {
          await window.pywebview.api.copy_to_clipboard(text);
          return;
        }
      } catch (_) {
        /* fallback */
      }
      try {
        await navigator.clipboard.writeText(text);
      } catch (_) {
        /* ignore */
      }
    },
    [],
  );

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;

    pinToBottom();

    if (waitingUserInput) {
      setMessages((prev) => [...prev, { role: 'user', content: text }]);
      callApi('submit_user_input', text);
      setWaitingUserInput(null);
      setInput('');
      return;
    }

    // 標記忙碌，期間禁止 health check 打到 LLM server
    isBusyRef.current = true;
    isStreamingRef.current = true;

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text },
      { role: 'agent', content: '', isStreaming: true },
    ]);
    callApi('send_prompt', text);
    setInput('');
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-50 font-sans text-sm text-zinc-900 antialiased selection:bg-zinc-200 dark:bg-zinc-950 dark:text-zinc-100 dark:selection:bg-zinc-700">
      <SideBar
        isCollapsed={sidebarCollapsed}
        setIsCollapsed={handleSidebarCollapse}
        baseUrl={baseUrl}
        setBaseUrl={setBaseUrl}
        modelName={modelName}
        setModelName={setModelName}
        applyApiConfig={() => {
          callApi('update_api_config', baseUrl, 'lm-studio', modelName);
        }}
        serverStatus={serverStatus}
        checkServerHealth={checkServerHealth}
        executionMode={executionMode}
        handleModeChange={(mode) => {
          setExecutionMode(mode);
          callApi('set_execution_mode', mode);
        }}
        clearDrawings={() => callApi('clear_drawings')}
        clearHistory={() => {
          clearMessages();
          callApi('clear_history');
        }}
        showLogWindow={showLog}
        setShowLogWindow={setShowLog}
        theme={theme}
        toggleTheme={toggleTheme}
      />

      <main className="relative flex min-w-0 flex-1 flex-col bg-zinc-50 dark:bg-zinc-950">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-5 md:px-6"
        >
          {messages.map((msg, i) => (
            <ChatMessage
              key={i}
              msg={msg}
              isLast={i === messages.length - 1}
              waitingConfirm={waitingConfirm}
              onConfirmStep={() => {
                setWaitingConfirm(false);
                callApi('confirm_step');
              }}
              onCopy={handleCopy}
            />
          ))}
          <div ref={chatEndRef} />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          waitingUserInput={waitingUserInput}
        />
      </main>

      {showLog && <LogPanel logs={logs} onClose={() => setShowLog(false)} />}
    </div>
  );
}
