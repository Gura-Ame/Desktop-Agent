import { useCallback, useEffect, useRef, useState } from 'react';
import ChatInput from './components/ChatInput';
import ChatMessage from './components/ChatMessage';
import LogPanel from './components/LogPanel';
import SideBar from './components/SideBar';
import { useAgentChat } from './hooks/useAgentChat';
import { usePywebview } from './hooks/usePywebview';
import { useTheme } from './hooks/useTheme';
import type { AgentEvent, ChatImage, ClientMode, ExecutionMode } from './types';

/** 視窗寬度低於此值時自動收合側欄 */
const SIDEBAR_AUTO_COLLAPSE_PX = 900;

export default function App() {
  const [input, setInput] = useState('');
  const [pendingImages, setPendingImages] = useState<ChatImage[]>([]);
  const [agentBusy, setAgentBusy] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX,
  );
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('STEP_BY_STEP');
  const [forgettingEnabled, setForgettingEnabled] = useState(false);
  const [activationEnabled, setActivationEnabled] = useState(false);
  const [clientMode, setClientMode] = useState<ClientMode>('local_llama');
  const [baseUrl, setBaseUrl] = useState('http://localhost:12356/v1');
  const [apiKey, setApiKey] = useState('lm-studio');
  const [modelName, setModelName] = useState('local-model');
  const [modelPath, setModelPath] = useState(
    String(import.meta.env.VITE_DEFAULT_MODEL_PATH ?? ''),
  );

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
    editUserMessage,
    switchFork,
  } = useAgentChat();

  const onAgentEvent = useCallback(
    (event: AgentEvent) => {
      handleAgentEvent(event);
      if (event?.type === 'finished' || event?.type === 'ask_confirm') {
        // ask_confirm 仍算等待中；finished 才真正結束
        if (event.type === 'finished') setAgentBusy(false);
      }
      if (event?.type === 'started' || event?.type === 'chunk') {
        setAgentBusy(true);
      }
    },
    [handleAgentEvent],
  );

  const { callApi } = usePywebview({
    onEvent: onAgentEvent,
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

  const handleSidebarCollapse = useCallback((collapsed: boolean) => {
    userPreferCollapsedRef.current = collapsed;
    autoCollapsedRef.current = false;
    setSidebarCollapsed(collapsed);
  }, []);

  /**
   * 檢查 LLM 伺服器狀態。
   * local_llama 模式下不走 HTTP，直接顯示「本地模型載入中」。
   * 嚴禁在 agent / 串流工作中對 server 發請求，否則可能把本地 llama 打掛。
   */
  const checkServerHealth = useCallback(async () => {
    if (isBusyRef.current || isStreamingRef.current) return;

    if (clientMode === 'local_llama') {
      // 無 HTTP server，直接反映本地模型狀態
      setServerStatus({ running: true, msg: '本地模型' });
      return;
    }

    try {
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
      if (!isBusyRef.current && !isStreamingRef.current) {
        setServerStatus({ running: false, msg: '離線' });
      }
    }
  }, [clientMode, baseUrl, isBusyRef, isStreamingRef, setServerStatus]);

  useEffect(() => {
    checkServerHealth();
    const id = setInterval(checkServerHealth, 15000);
    return () => clearInterval(id);
  }, [checkServerHealth]);

  const handleCopy = useCallback(
    async (text: string) => {
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
    },
    [],
  );

  const handleStop = () => {
    callApi('stop_agent');
    isBusyRef.current = false;
    isStreamingRef.current = false;
    setAgentBusy(false);
    setWaitingConfirm(false);
    setWaitingUserInput(null);
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === 'agent' && last.isStreaming) {
        next[next.length - 1] = {
          ...last,
          isStreaming: false,
          content: (last.content || '') + '\n\n*(已停止)*',
        };
      }
      return next;
    });
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text && pendingImages.length === 0) return;

    pinToBottom();
    const ts = Date.now();
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    // 壓縮圖片，避免本地 VL GGUF 吃大圖吐 ????
    const { compressImages } = await import('./lib/imageUtils');
    const images = await compressImages(
      pendingImages.map((img) => ({
        id: img.id,
        name: img.name,
        dataUrl: img.dataUrl,
      })),
    );

    const prompt =
      text ||
      (images.length
        ? 'Please describe what you see in the image in detail.'
        : '');
    const imageUrls = images.map((img) => img.dataUrl).filter(Boolean);

    if (waitingUserInput) {
      setMessages((prev) => [
        ...prev,
        { id, role: 'user', content: text, images, ts },
      ]);
      callApi('submit_user_input', prompt);
      setWaitingUserInput(null);
      setInput('');
      setPendingImages([]);
      return;
    }

    isBusyRef.current = true;
    isStreamingRef.current = true;
    setAgentBusy(true);

    setMessages((prev) => [
      ...prev,
      { id, role: 'user', content: text, images, ts },
      {
        id: `${id}-a`,
        role: 'agent',
        content: '',
        isStreaming: true,
        ts,
      },
    ]);
    callApi('send_prompt', prompt, imageUrls);
    setInput('');
    setPendingImages([]);
  };
  // Open Chrome incognito search
  const openChromeIncognito = (query: string) => {
    callApi('open_chrome_incognito', query);
  };


  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#e8e8ea] font-sans text-sm text-zinc-900 antialiased selection:bg-zinc-300 dark:bg-[#1c1c1e] dark:text-zinc-100 dark:selection:bg-zinc-600">
      <SideBar
        isCollapsed={sidebarCollapsed}
        setIsCollapsed={handleSidebarCollapse}
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
        applyApiConfig={() => {
          if (clientMode === 'local_llama') {
            callApi('load_llama_model', modelPath);
          } else if (clientMode === 'local_server') {
            callApi('toggle_local_server', modelPath);
          } else {
            callApi('update_api_config', baseUrl, apiKey, modelName);
          }
        }}
        openChromeIncognito={openChromeIncognito}
        serverStatus={serverStatus}
        checkServerHealth={checkServerHealth}
        executionMode={executionMode}
        handleModeChange={(mode) => {
          setExecutionMode(mode);
          callApi('set_execution_mode', mode);
        }}
        forgettingEnabled={forgettingEnabled}
        handleForgettingToggle={(enabled) => {
          setForgettingEnabled(enabled);
          callApi('set_forgetting_enabled', enabled);
        }}
        activationEnabled={activationEnabled}
        handleActivationToggle={(enabled) => {
          setActivationEnabled(enabled);
          callApi('set_activation_enabled', enabled);
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

      <main className="relative flex min-w-0 flex-1 flex-col bg-[#e8e8ea] dark:bg-[#1c1c1e]">
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-5 md:px-6"
        >
          {messages.map((msg, i) => (
            <ChatMessage
              key={msg.id || i}
              msg={msg}
              isLast={i === messages.length - 1}
              waitingConfirm={waitingConfirm}
              onConfirmStep={() => {
                setWaitingConfirm(false);
                setAgentBusy(true);
                isBusyRef.current = true;
                callApi('confirm_step');
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
                pinToBottom();
                isBusyRef.current = true;
                isStreamingRef.current = true;
                setAgentBusy(true);
                const imgs = payload?.images || [];
                callApi(
                  'send_prompt',
                  payload?.text || nextText,
                  imgs,
                );
              }}
            />
          ))}
          <div ref={chatEndRef} />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          onStop={handleStop}
          waitingUserInput={waitingUserInput}
          isBusy={agentBusy || waitingConfirm}
          images={pendingImages}
          onAddImages={(list) => setPendingImages((prev) => [...prev, ...list])}
          onRemoveImage={(id) =>
            setPendingImages((prev) => prev.filter((img) => img.id !== id))
          }
        />
      </main>

      {showLog && <LogPanel logs={logs} onClose={() => setShowLog(false)} />}
    </div>
  );
}
