import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { AgentEvent, ExecutionMode } from '../types';

function isBridgeReady() {
  const api = window.pywebview?.api;
  return !!(api && typeof api.poll_events === 'function');
}

type PendingCall = {
  method: string;
  args: unknown[];
};

type UsePywebviewArgs = {
  onEvent?: (event: AgentEvent) => void;
  executionModeRef?: RefObject<ExecutionMode>;
};

/**
 * pywebview bridge：就緒偵測、排隊呼叫、事件輪詢、複製攔截。
 */
export function usePywebview({ onEvent, executionModeRef }: UsePywebviewArgs) {
  const [apiReady, setApiReady] = useState(false);
  const pendingCallsRef = useRef<PendingCall[]>([]);

  // 等 bridge 真正可用
  useEffect(() => {
    const tryReady = () => {
      if (isBridgeReady()) {
        setApiReady(true);
        return true;
      }
      return false;
    };

    if (tryReady()) return undefined;

    const onReady = () => {
      if (tryReady()) return;
      let n = 0;
      const id = setInterval(() => {
        n += 1;
        if (tryReady() || n > 40) clearInterval(id);
      }, 50);
    };

    window.addEventListener('pywebviewready', onReady);
    const pollId = setInterval(() => {
      if (tryReady()) clearInterval(pollId);
    }, 100);

    return () => {
      window.removeEventListener('pywebviewready', onReady);
      clearInterval(pollId);
    };
  }, []);

  // 就緒後沖出排隊 + 同步執行模式
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

    const fn = window.pywebview?.api?.set_execution_mode;
    if (typeof fn === 'function' && executionModeRef?.current) {
      try {
        fn(executionModeRef.current);
      } catch {
        /* ignore */
      }
    }
  }, [apiReady, executionModeRef]);

  // 輪詢事件
  useEffect(() => {
    if (!apiReady || !onEvent) return undefined;

    let cancelled = false;
    const poll = async () => {
      if (cancelled) return;
      try {
        const events = await window.pywebview?.api?.poll_events?.();
        if (events?.length) {
          for (const ev of events) onEvent(ev);
        }
      } catch {
        /* bridge 短暫不可用 */
      }
    };

    const id = setInterval(poll, 50);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [apiReady, onEvent]);

  // 相容舊 onAgentEvent 路徑
  useEffect(() => {
    if (onEvent) window.onAgentEvent = onEvent;
  }, [onEvent]);

  const callApi = useCallback(
    (method: string, ...args: unknown[]) => {
      if (!apiReady || !isBridgeReady()) {
        pendingCallsRef.current.push({ method, args });
        return undefined;
      }
      const fn = window.pywebview?.api?.[method];
      if (typeof fn !== 'function') {
        console.warn('[pywebview] method not found:', method);
        return undefined;
      }
      return fn(...args);
    },
    [apiReady],
  );

  return { apiReady, callApi };
}
