/// <reference types="vite/client" />

import type { AgentEvent } from "./types";

type PywebviewFn = (...args: unknown[]) => unknown;

export type PywebviewApi = {
	ping?: () =>
		| Promise<{ status: string; msg?: string } | undefined>
		| { status: string; msg?: string };
	poll_events?: () => Promise<AgentEvent[] | undefined>;
	copy_to_clipboard?: (text: string) => Promise<unknown> | unknown;
	send_prompt?: (...args: unknown[]) => unknown;
	stop_agent?: (...args: unknown[]) => unknown;
	pick_files?: () => Promise<string[]> | string[];
	pick_model_file?: () => Promise<string> | string;
	get_llm_status?: () => Promise<{ status: string; is_llama: boolean; model_loaded: boolean; model_name: string }>;
	load_llama_model?: (model_path: string, n_ctx?: number, n_gpu_layers?: number) => Promise<{ status: string; model_name?: string; msg?: string }>;
	log_from_frontend?: (level: string, message: string) => Promise<unknown> | unknown;
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
		__devConsoleBridgeInstalled?: boolean;
	}
}
