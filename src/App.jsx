import { useEffect, useRef, useState } from 'react';
import ChatInput from './components/ChatInput';
import ChatMessage from './components/ChatMessage';
import LogPanel from './components/LogPanel';
import SideBar from './components/SideBar';
import { useAgentChat } from './hooks/useAgentChat';
import { usePywebview } from './hooks/usePywebview';
import { useTheme } from './hooks/useTheme';

export default function App() {
  const [input, setInput] = useState('');
  const [showLog, setShowLog] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [executionMode, setExecutionMode] = useState('STEP_BY_STEP');
  const [baseUrl, setBaseUrl] = useState('http://localhost:12356/v1');
  const [modelName, setModelName] = useState('local-model');

  const executionModeRef = useRef(executionMode);
  executionModeRef.current = executionMode;

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
    handleAgentEvent,
    clearMessages,
  } = useAgentChat();

  const { callApi } = usePywebview({
    onEvent: handleAgentEvent,
    executionModeRef,
  });

  useEffect(() => {
    const check = () => {
      if (isStreamingRef.current) return;
      setServerStatus({ running: true, msg: '在線' });
    };
    check();
    const id = setInterval(check, 10000);
    return () => clearInterval(id);
  }, [baseUrl, isStreamingRef, setServerStatus]);

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
        setIsCollapsed={setSidebarCollapsed}
        baseUrl={baseUrl}
        setBaseUrl={setBaseUrl}
        modelName={modelName}
        setModelName={setModelName}
        applyApiConfig={() => {
          callApi('update_api_config', baseUrl, 'lm-studio', modelName);
        }}
        serverStatus={serverStatus}
        checkServerHealth={() => setServerStatus({ running: true, msg: '在線' })}
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
