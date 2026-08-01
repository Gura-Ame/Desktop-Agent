import { Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import ChatMessage from './components/ChatMessage';
import LogPanel from './components/LogPanel';
import SideBar from './components/SideBar';

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: 'agent',
      content: '**你好！** 我是您的 AI 桌面自動化常駐助理。'
    }
  ]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [logs, setLogs] = useState([]);
  const [showLogWindow, setShowLogWindow] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  // 與後端 AgentWorker 預設、SideBar 選項一致
  const [executionMode, setExecutionMode] = useState('STEP_BY_STEP');
  const [serverStatus, setServerStatus] = useState({ running: false, msg: '檢查中...' });

  const [baseUrl, setBaseUrl] = useState('http://localhost:12356/v1');
  const [modelName, setModelName] = useState('local-model');

  const [waitingConfirm, setWaitingConfirm] = useState(false);
  const [waitingUserInput, setWaitingUserInput] = useState(null);
  const [apiReady, setApiReady] = useState(false);

  const chatEndRef = useRef(null);
  const isStreamingRef = useRef(false);
  // bridge 未就緒時暫存的 API 呼叫，就緒後一次沖出
  const pendingCallsRef = useRef([]);
  const executionModeRef = useRef(executionMode);
  executionModeRef.current = executionMode;

  const handleAgentEvent = (event) => {
    const { type, data } = event;

    switch (type) {
      case 'chunk':
        isStreamingRef.current = true;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'agent' && last.isStreaming) {
            return [...prev.slice(0, -1), { ...last, content: last.content + data }];
          }
          return [...prev, { role: 'agent', content: data, isStreaming: true }];
        });
        break;

      case 'finished':
        isStreamingRef.current = false;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'agent') {
            return [...prev.slice(0, -1), { ...last, isStreaming: false }];
          }
          return prev;
        });
        break;

      case 'log':
        setLogs((prev) => [...prev, data]);
        break;

      case 'server_status':
        setServerStatus(data);
        break;

      case 'ask_confirm':
        setWaitingConfirm(true);
        setMessages((prev) => [
          ...prev,
          { role: 'agent', content: `\n\`\`\`text\n${data}\n\`\`\``, isTree: true }
        ]);
        break;

      case 'waiting_input':
        setWaitingUserInput(data);
        break;

      default:
        break;
    }
  };

  const isBridgeReady = () => {
    const api = window.pywebview?.api;
    return !!(api && typeof api.poll_events === 'function');
  };

  // 等 pywebview bridge 真正可用（方法已掛上）
  useEffect(() => {
    const tryReady = () => {
      if (isBridgeReady()) {
        setApiReady(true);
        return true;
      }
      return false;
    };

    if (tryReady()) return;

    const onReady = () => {
      // pywebviewready 當下方法有時還沒掛完，再多試幾次
      if (tryReady()) return;
      let n = 0;
      const id = setInterval(() => {
        n += 1;
        if (tryReady() || n > 40) clearInterval(id);
      }, 50);
    };

    window.addEventListener('pywebviewready', onReady);
    // 保底輪詢（Vite HMR / 時序差異）
    const pollId = setInterval(() => {
      if (tryReady()) clearInterval(pollId);
    }, 100);

    return () => {
      window.removeEventListener('pywebviewready', onReady);
      clearInterval(pollId);
    };
  }, []);

  // bridge 就緒後：沖出排隊中的呼叫，並同步目前執行模式
  useEffect(() => {
    if (!apiReady) return;

    const pending = pendingCallsRef.current;
    pendingCallsRef.current = [];
    for (const { method, args } of pending) {
      const fn = window.pywebview?.api?.[method];
      if (typeof fn === 'function') {
        try {
          fn(...args);
        } catch (e) {
          console.warn('[pywebview] pending call failed:', method, e);
        }
      }
    }

    // 把前端目前的 mode 同步到後端（靜默，不產生 not ready 警告）
    const fn = window.pywebview?.api?.set_execution_mode;
    if (typeof fn === 'function') {
      try {
        fn(executionModeRef.current);
      } catch (_) {
        /* ignore */
      }
    }
  }, [apiReady]);

  // 用 poll 拉事件：不依賴 evaluate_js / QTimer，可避開 PyQt5/6 混用
  useEffect(() => {
    if (!apiReady) return;

    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      try {
        const events = await window.pywebview?.api?.poll_events?.();
        if (events && Array.isArray(events) && events.length > 0) {
          for (const ev of events) {
            handleAgentEvent(ev);
          }
        }
      } catch (err) {
        // bridge 尚未完全可用時略過
      }
    };

    const id = setInterval(poll, 50);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [apiReady]);

  // 仍保留 onAgentEvent，相容舊路徑（若有）
  useEffect(() => {
    window.onAgentEvent = handleAgentEvent;
  }, []);

  // 攔截複製：改走 Python Win32 剪貼簿，避開 Qt WebEngine OleSetClipboard COM 錯誤
  useEffect(() => {
    const onCopy = (e) => {
      const sel = window.getSelection?.()?.toString();
      if (!sel) return;
      // 優先走我們的 API
      if (window.pywebview?.api?.copy_to_clipboard) {
        try {
          window.pywebview.api.copy_to_clipboard(sel);
          e.clipboardData?.setData('text/plain', sel);
          e.preventDefault();
        } catch (_) {
          /* 失敗則讓瀏覽器預設行為繼續 */
        }
      }
    };
    document.addEventListener('copy', onCopy);
    return () => document.removeEventListener('copy', onCopy);
  }, []);

  const checkServerHealth = async () => {
    if (isStreamingRef.current) return;
    try {
      setServerStatus({ running: true, msg: '在線 (API 就緒)' });
    } catch {
      setServerStatus({ running: false, msg: '離線 / 無法連線' });
    }
  };

  useEffect(() => {
    checkServerHealth();
    const interval = setInterval(checkServerHealth, 10000);
    return () => clearInterval(interval);
  }, [baseUrl]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const callApi = (method, ...args) => {
    if (!apiReady || !isBridgeReady()) {
      // 未就緒：排隊，不刷 console
      pendingCallsRef.current.push({ method, args });
      return;
    }
    const fn = window.pywebview.api[method];
    if (typeof fn !== 'function') {
      console.warn('[pywebview] method not found:', method);
      return;
    }
    return fn(...args);
  };

  const handleSend = () => {
    if (!inputPrompt.trim()) return;

    if (waitingUserInput) {
      setMessages((prev) => [...prev, { role: 'user', content: inputPrompt }]);
      callApi('submit_user_input', inputPrompt);
      setWaitingUserInput(null);
      setInputPrompt('');
      return;
    }

    setMessages((prev) => [
      ...prev,
      { role: 'user', content: inputPrompt },
      { role: 'agent', content: '', isStreaming: true }
    ]);

    callApi('send_prompt', inputPrompt);
    setInputPrompt('');
  };

  const applyApiConfig = () => {
    callApi('update_api_config', baseUrl, 'lm-studio', modelName);
    checkServerHealth();
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100 font-sans text-sm selection:bg-zinc-800">

      <SideBar
        isCollapsed={isSidebarCollapsed}
        setIsCollapsed={setIsSidebarCollapsed}
        baseUrl={baseUrl}
        setBaseUrl={setBaseUrl}
        modelName={modelName}
        setModelName={setModelName}
        applyApiConfig={applyApiConfig}
        serverStatus={serverStatus}
        checkServerHealth={checkServerHealth}
        executionMode={executionMode}
        handleModeChange={(mode) => {
          setExecutionMode(mode);
          callApi('set_execution_mode', mode);
        }}
        clearDrawings={() => callApi('clear_drawings')}
        clearHistory={() => {
          setMessages([]);
          callApi('clear_history');
        }}
        showLogWindow={showLogWindow}
        setShowLogWindow={setShowLogWindow}
      />

      <main className="flex-1 flex flex-col min-w-0 h-full bg-zinc-950 relative">
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4 min-h-0 min-w-0">
          {messages.map((msg, index) => (
            <ChatMessage
              key={index}
              msg={msg}
              isLast={index === messages.length - 1}
              waitingConfirm={waitingConfirm}
              onConfirmStep={() => {
                setWaitingConfirm(false);
                callApi('confirm_step');
              }}
            />
          ))}
          <div ref={chatEndRef} />
        </div>

        <div className="p-4 border-t border-zinc-800/80 bg-zinc-950/80 backdrop-blur shrink-0">
          <div className="max-w-4xl mx-auto space-y-2">
            {waitingUserInput && (
              <div className="text-amber-400 text-xs flex items-center gap-1.5 bg-amber-500/10 border border-amber-500/20 px-3 py-1.5 rounded-lg">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                <span>Agent 提問：{waitingUserInput}</span>
              </div>
            )}

            <div className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-xl px-3 py-1.5 shadow-sm focus-within:border-zinc-700 transition-all">
              <input
                type="text"
                value={inputPrompt}
                onChange={(e) => setInputPrompt(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={waitingUserInput ? "請輸入回答..." : "輸入指令..."}
                className="flex-1 bg-transparent text-sm text-zinc-100 placeholder:text-zinc-500 outline-none py-1.5"
              />
              <button
                onClick={handleSend}
                disabled={!inputPrompt.trim()}
                className="p-2 rounded-lg bg-zinc-100 hover:bg-white text-zinc-950 disabled:opacity-30 transition-all shrink-0"
              >
                <Send size={15} />
              </button>
            </div>
          </div>
        </div>
      </main>

      {showLogWindow && (
        <LogPanel logs={logs} onClose={() => setShowLogWindow(false)} />
      )}
    </div>
  );
}
