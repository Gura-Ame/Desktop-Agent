import { useCallback, useEffect, useRef, useState } from 'react';

const WELCOME = {
  role: 'agent',
  content: '**你好！** 我是您的 AI 桌面自動化常駐助理。',
};

const NEAR_BOTTOM_PX = 80;

/**
 * 對話狀態 + agent 事件處理。
 * 自動捲動：只有使用者接近底部時才跟著往下；往上捲看歷史時不會被強制拉回。
 */
export function useAgentChat() {
  const [messages, setMessages] = useState([WELCOME]);
  const [logs, setLogs] = useState([]);
  const [waitingConfirm, setWaitingConfirm] = useState(false);
  const [waitingUserInput, setWaitingUserInput] = useState(null);
  const [serverStatus, setServerStatus] = useState({
    running: false,
    msg: '檢查中...',
  });

  const chatEndRef = useRef(null);
  const scrollContainerRef = useRef(null);
  const isStreamingRef = useRef(false);
  const stickToBottomRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance <= NEAR_BOTTOM_PX;
  }, []);

  const scrollToBottom = useCallback((behavior = 'smooth') => {
    const el = scrollContainerRef.current;
    if (!el) {
      chatEndRef.current?.scrollIntoView({ behavior });
      return;
    }
    if (behavior === 'auto') {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, []);

  const handleAgentEvent = useCallback((event) => {
    const { type, data } = event;

    switch (type) {
      case 'chunk':
        isStreamingRef.current = true;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === 'agent' && last.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + data },
            ];
          }
          return [...prev, { role: 'agent', content: data, isStreaming: true }];
        });
        break;

      case 'finished':
        isStreamingRef.current = false;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === 'agent') {
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
          {
            role: 'agent',
            content: `\n\`\`\`text\n${data}\n\`\`\``,
            isTree: true,
          },
        ]);
        break;

      case 'waiting_input':
        setWaitingUserInput(data);
        break;

      default:
        break;
    }
  }, []);

  // 只在「貼近底部」時自動捲動；串流中用 instant 避免抖動
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const behavior = isStreamingRef.current ? 'auto' : 'smooth';
    // rAF：等 DOM 更新完再捲
    const id = requestAnimationFrame(() => scrollToBottom(behavior));
    return () => cancelAnimationFrame(id);
  }, [messages, scrollToBottom]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setWaitingConfirm(false);
    setWaitingUserInput(null);
    stickToBottomRef.current = true;
  }, []);

  /** 送出新訊息前呼叫，強制貼底 */
  const pinToBottom = useCallback(() => {
    stickToBottomRef.current = true;
  }, []);

  return {
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
  };
}
