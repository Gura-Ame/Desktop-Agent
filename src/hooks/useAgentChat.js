import { useCallback, useEffect, useRef, useState } from 'react';

function nowTs() {
  return Date.now();
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

const WELCOME = {
  id: 'welcome',
  role: 'agent',
  content: '**你好！** 我是您的 AI 桌面自動化常駐助理。',
  ts: Date.now(),
};

const NEAR_BOTTOM_PX = 80;

/**
 * 對話狀態 + agent 事件 + 分枝。
 *
 * 分枝模型：
 * - 每則 user 訊息可有 `forks: { content, images, tail }[]`
 * - `forkIndex` 指向目前作用中的分支
 * - `tail` 是該分支在此 user 訊息之後的後續訊息
 * - 主線 `messages` 永遠是「目前選中的完整路徑」
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
  const isBusyRef = useRef(false);
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
      case 'started':
        isBusyRef.current = true;
        break;

      case 'chunk':
        isStreamingRef.current = true;
        isBusyRef.current = true;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === 'agent' && last.isStreaming) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + data },
            ];
          }
          return [
            ...prev,
            { id: uid(), role: 'agent', content: data, isStreaming: true, ts: nowTs() },
          ];
        });
        break;

      case 'finished':
        isStreamingRef.current = false;
        isBusyRef.current = false;
        setWaitingConfirm(false);
        setWaitingUserInput(null);
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === 'agent') {
            return [
              ...prev.slice(0, -1),
              { ...last, isStreaming: false, ts: last.ts || nowTs() },
            ];
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
        isBusyRef.current = true;
        isStreamingRef.current = false;
        setWaitingConfirm(true);
        setMessages((prev) => {
          const next = [...prev];
          while (next.length > 0) {
            const last = next[next.length - 1];
            if (last.role === 'agent' && last.isStreaming && !last.content?.trim()) {
              next.pop();
              continue;
            }
            if (last.role === 'agent' && last.isStreaming) {
              next[next.length - 1] = { ...last, isStreaming: false };
            }
            break;
          }
          next.push({
            id: uid(),
            role: 'agent',
            content: typeof data === 'string' ? data : String(data ?? ''),
            isTree: true,
            isStreaming: false,
            ts: nowTs(),
          });
          return next;
        });
        break;

      case 'waiting_input':
        isBusyRef.current = true;
        isStreamingRef.current = false;
        setWaitingUserInput(data);
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last?.role === 'agent' && last.isStreaming) {
            next[next.length - 1] = { ...last, isStreaming: false };
          }
          next.push({
            id: uid(),
            role: 'agent',
            content: `**❓ 需要你的協助**\n\n${data}`,
            isQuestion: true,
            ts: nowTs(),
          });
          return next;
        });
        break;

      default:
        break;
    }
  }, []);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const behavior = isStreamingRef.current ? 'auto' : 'smooth';
    const id = requestAnimationFrame(() => scrollToBottom(behavior));
    return () => cancelAnimationFrame(id);
  }, [messages, scrollToBottom]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setWaitingConfirm(false);
    setWaitingUserInput(null);
    isBusyRef.current = false;
    isStreamingRef.current = false;
    stickToBottomRef.current = true;
  }, []);

  const pinToBottom = useCallback(() => {
    stickToBottomRef.current = true;
  }, []);

  /**
   * 編輯 user 訊息；resend=true 時建立新分枝並回傳要送給 LLM 的文字與圖片。
   */
  const editUserMessage = useCallback((msg, nextText, resend) => {
    let payload = null;

    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === msg.id || m === msg);
      if (idx < 0) return prev;

      if (!resend) {
        const next = [...prev];
        next[idx] = { ...next[idx], content: nextText };
        return next;
      }

      // --- 建立分枝 ---
      const head = prev.slice(0, idx);
      const oldUser = prev[idx];
      const oldTail = prev.slice(idx + 1);

      // 舊分支：原 user 內容 + 之後的訊息
      const oldFork = {
        id: uid(),
        content: oldUser.content,
        images: oldUser.images || [],
        tail: oldTail,
      };

      // 既有 forks（若這則已經是分枝點）
      const existingForks = oldUser.forks ? [...oldUser.forks] : [];
      // 若還沒有 forks，把「目前這條」存成第 0 支
      if (existingForks.length === 0 && (oldTail.length > 0 || oldUser.content !== nextText)) {
        existingForks.push(oldFork);
      } else if (existingForks.length > 0) {
        // 更新目前作用中那支的 tail 為當前 tail
        const fi = oldUser.forkIndex ?? existingForks.length - 1;
        existingForks[fi] = {
          ...existingForks[fi],
          content: oldUser.content,
          images: oldUser.images || [],
          tail: oldTail,
        };
      }

      // 新分支
      const newFork = {
        id: uid(),
        content: nextText,
        images: oldUser.images || [],
        tail: [],
      };
      const forks = [...existingForks, newFork];
      const forkIndex = forks.length - 1;

      const newUser = {
        ...oldUser,
        content: nextText,
        forks,
        forkIndex,
        ts: nowTs(),
      };

      const agentPlaceholder = {
        id: uid(),
        role: 'agent',
        content: '',
        isStreaming: true,
        ts: nowTs(),
      };

      payload = {
        text: nextText,
        images: (oldUser.images || []).map((img) => img.dataUrl).filter(Boolean),
      };

      return [...head, newUser, agentPlaceholder];
    });

    return payload;
  }, []);

  /**
   * 在分枝點切換 fork（◀ ▶）
   */
  const switchFork = useCallback((msgId, direction) => {
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === msgId);
      if (idx < 0) return prev;
      const user = prev[idx];
      if (!user.forks?.length) return prev;

      const cur = user.forkIndex ?? 0;
      // 先把目前 tail 存回 forks[cur]
      const currentTail = prev.slice(idx + 1);
      const forks = user.forks.map((f, i) =>
        i === cur
          ? { ...f, content: user.content, images: user.images || [], tail: currentTail }
          : f,
      );

      const nextIdx =
        direction === 'prev'
          ? (cur - 1 + forks.length) % forks.length
          : (cur + 1) % forks.length;

      const target = forks[nextIdx];
      const restoredUser = {
        ...user,
        content: target.content,
        images: target.images || [],
        forks,
        forkIndex: nextIdx,
      };

      return [...prev.slice(0, idx), restoredUser, ...(target.tail || [])];
    });
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
    isBusyRef,
    handleAgentEvent,
    clearMessages,
    editUserMessage,
    switchFork,
  };
}
