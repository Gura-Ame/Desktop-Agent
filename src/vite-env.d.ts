/// <reference types="vite/client" />

import type { AgentEvent } from "./types";

type PywebviewFn = (...args: unknown[]) => unknown;

export type PywebviewApi = {
	poll_events?: () => Promise<AgentEvent[] | undefined>;
	copy_to_clipboard?: (text: string) => Promise<void> | void;
	[method: string]: PywebviewFn | undefined;
};

declare global {
	interface Window {
		pywebview?: {
			api?: PywebviewApi;
		};
		onAgentEvent?: (event: AgentEvent) => void;
	}
}

export {};
