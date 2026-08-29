/// <reference types="vite/client" />

import type { AgentEvent } from './types';

type PywebviewFn = (...args: unknown[]) => unknown;

export type PywebviewApi = {
  ping?: () => Promise<{ status: string; msg?: string } | undefined> | { status: string; msg?: string };
  poll_events?: () => Promise<AgentEvent[] | undefined>;
  copy_to_clipboard?: (text: string) => Promise<unknown> | unknown;
  send_prompt?: (...args: unknown[]) => unknown;
  stop_agent?: (...args: unknown[]) => unknown;
  [method: string]: PywebviewFn | undefined;
};

declare global {
  interface Window {
    pywebview?: {
      api?: PywebviewApi;
      platform?: string;
      token?: string;
    };
    onAgentEvent?: (event: AgentEvent) => void;
  }
}

export {};
