export type Theme = 'light' | 'dark';

export type ExecutionMode = 'STEP_BY_STEP' | 'SMART' | 'AUTO';

export type ChatImage = {
  id: string;
  name: string;
  mime?: string;
  dataUrl: string;
};

export type ChatMessage = {
  id: string;
  role: 'user' | 'agent';
  content: string;
  ts?: number;
  isStreaming?: boolean;
  isTree?: boolean;
  isQuestion?: boolean;
  images?: ChatImage[];
  forks?: MessageFork[];
  forkIndex?: number;
};

export type MessageFork = {
  id: string;
  content: string;
  images: ChatImage[];
  tail: ChatMessage[];
};

export type ServerStatus = {
  running: boolean;
  msg: string;
};

export type AgentEvent = {
  type: string;
  data?: unknown;
};

export type ToolStatus = 'running' | 'success' | 'error';

export type TextBlock = {
  type: 'text';
  content: string;
};

export type ToolBlock = {
  type: 'tool';
  funcName: string;
  args: string;
  result: string | null;
  status: ToolStatus;
};

export type MessageBlock = TextBlock | ToolBlock;

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'decomposed'
  | 'failed';

export type ParsedTask = {
  id: string;
  title: string;
  status: TaskStatus;
  depth: number;
  method: string;
  condition: string;
  note: string;
  result: string;
  needThinking: boolean;
  needDecompose: boolean;
  needConfirm: boolean;
  confidence: number;
};

export type EditUserPayload = {
  text: string;
  images: string[];
};

export type ForkDirection = 'prev' | 'next';

export type ClientMode = 'local_llama' | 'local_server' | 'remote_api';

