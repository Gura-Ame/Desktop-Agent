import { useCallback, useRef, useState } from 'react';
import { useChatScroll } from './chat/useChatScroll';
import { useAgentEventHandler } from './chat/useAgentEventHandler';

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

  const isStreamingRef = useRef(false);
  const isBusyRef = useRef(false);

  const {
    chatEndRef,
    scrollContainerRef,
    stickToBottomRef,
    handleScroll,
    pinToBottom,
  } = useChatScroll(messages, isStreamingRef);

  const { handleAgentEvent } = useAgentEventHandler({
    setMessages,
    setLogs,
    setWaitingConfirm,
    setWaitingUserInput,
    setServerStatus,
    isStreamingRef,
    isBusyRef,
  });

  const clearMessages = useCallback(() => {
    setMessages([]);
    setWaitingConfirm(false);
    setWaitingUserInput(null);
    isBusyRef.current = false;
    isStreamingRef.current = false;
    stickToBottomRef.current = true;
  }, [stickToBottomRef]);

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

      const oldFork = {
        id: uid(),
        content: oldUser.content,
        images: oldUser.images || [],
        tail: oldTail,
      };

      const existingForks = oldUser.forks ? [...oldUser.forks] : [];
      if (existingForks.length === 0 && (oldTail.length > 0 || oldUser.content !== nextText)) {
        existingForks.push(oldFork);
      } else if (existingForks.length > 0) {
        const fi = oldUser.forkIndex ?? existingForks.length - 1;
        existingForks[fi] = {
          ...existingForks[fi],
          content: oldUser.content,
          images: oldUser.images || [],
          tail: oldTail,
        };
      }

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
