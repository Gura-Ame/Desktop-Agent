import { useCallback, useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { AgentEvent, ExecutionMode } from '../types';

/**
 * pywebview 的 api 在 DevTools 裡常顯示成 {}（方法不可列舉），
 * 不能用 Object.keys / JSON.stringify 判斷；必須用 typeof fn === 'function'。
 */
function isBridgeReady(): boolean {
  const api = window.pywebview?.api as Record<string, unknown> | undefined;
  if (!api) return false;
  return typeof api.poll_events === 'function' || typeof api.ping === 'function';
}

function describeApi(): string {
  const api = window.pywebview?.api as Record<string, unknown> | undefined;
  if (!api) return 'pywebview.api = undefined';
  const names = new Set<string>([
    ...Object.keys(api),
    ...Object.getOwnPropertyNames(api),
  ]);
  // 再試一批已知方法（可能不可列舉）
  const known = [
    'ping',
    'poll_events',
    'send_prompt',
    'stop_agent',
    'confirm_step',
    'submit_user_input',
    'set_execution_mode',
    'copy_to_clipboard',
  ];
  const callable: string[] = [];
  for (const k of known) {
    if (typeof api[k] === 'function') callable.push(k);
  }
  return `keys=[${[...names].join(',')}] callable=[${callable.join(',')}]`;
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
 * pywebview bridge：就緒偵測、排隊呼叫、事件輪詢。
 */
export function usePywebview({ onEvent, executionModeRef }: UsePywebviewArgs) {
  const [apiReady, setApiReady] = useState(false);
  const pendingCallsRef = useRef<PendingCall[]>([]);
  const readyLoggedRef = useRef(false);

  // 等 bridge 真正可用（以 poll_events / ping 是否為 function 為準）
  useEffect(() => {
    let settled = false;

    const tryReady = () => {
      if (settled) return true;
      if (isBridgeReady()) {
        settled = true;
        setApiReady(true);
        if (!readyLoggedRef.current) {
          readyLoggedRef.current = true;
          console.info('[pywebview] bridge ready:', describeApi());
        }
        return true;
      }
      return false;
    };

    if (tryReady()) return undefined;

    const onReady = () => {
      // 事件觸發後再多輪詢幾次，Edge 有時事件先到、方法後掛
      let n = 0;
      const id = setInterval(() => {
        n += 1;
        if (tryReady() || n > 60) clearInterval(id);
      }, 50);
    };

    window.addEventListener('pywebviewready', onReady);

    const pollId = setInterval(() => {
      if (tryReady()) {
        clearInterval(pollId);
        return;
      }
    }, 100);

    // 逾時診斷：10 秒仍未就緒
    const diagId = setTimeout(() => {
      if (!settled) {
        console.warn(
          '[pywebview] bridge 仍未就緒。若你是在一般瀏覽器開 5173，不會有 api。',
          describeApi(),
          {
            hasPywebview: !!window.pywebview,
            platform: (window.pywebview as { platform?: string } | undefined)?.platform,
          },
        );
      }
    }, 10000);

    return () => {
      window.removeEventListener('pywebviewready', onReady);
      clearInterval(pollId);
      clearTimeout(diagId);
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
      } else {
        console.warn('[pywebview] pending method missing after ready:', method);
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
        console.debug('[pywebview] queued (not ready):', method);
        return undefined;
      }
      const fn = window.pywebview?.api?.[method];
      if (typeof fn !== 'function') {
        console.warn('[pywebview] method not found:', method, describeApi());
        return undefined;
      }
      return fn(...args);
    },
    [apiReady],
  );

  return { apiReady, callApi };
}
