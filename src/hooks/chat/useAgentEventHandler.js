import { useCallback } from 'react';

function nowTs() {
  return Date.now();
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function useAgentEventHandler({
  setMessages,
  setLogs,
  setWaitingConfirm,
  setWaitingUserInput,
  setServerStatus,
  isStreamingRef,
  isBusyRef,
}) {
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

      case 'chunk_patch':
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (!last || last.role !== 'agent') return prev;
          const { old, new: replacement } = data || {};
          if (typeof old !== 'string' || typeof replacement !== 'string') return prev;
          if (!last.content.endsWith(old)) return prev;
          const patched = last.content.slice(0, last.content.length - old.length) + replacement;
          return [...prev.slice(0, -1), { ...last, content: patched }];
        });
        break;

      case 'reset_message':
        // 後端放棄了目前這則還在串流中的內容（例如推理被截斷後改走 Planning，
        // 結果 Planning 也失敗，準備整個重新生成一次）。把這則清掉，
        // 讓接下來的 chunk 從一個乾淨的新泡泡開始，不要接在被放棄的內容後面
        // 造成「同一段話出現兩次」的錯覺。
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === 'agent' && last.isStreaming) {
            return prev.slice(0, -1);
          }
          return prev;
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
  }, [setMessages, setLogs, setWaitingConfirm, setWaitingUserInput, setServerStatus, isStreamingRef, isBusyRef]);

  return { handleAgentEvent };
}
