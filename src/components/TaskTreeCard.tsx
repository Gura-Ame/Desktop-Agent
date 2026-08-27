import type { ReactNode } from 'react';
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  GitBranch,
  ListTree,
  ShieldAlert,
} from 'lucide-react';
import { useState } from 'react';
import { parseTaskTreeMarkdown } from '../lib/parseTaskTree';
import { cn } from '../lib/utils';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import type { ParsedTask } from '../types';

const STATUS_LABEL: Record<
  ParsedTask['status'],
  { label: string; variant: 'default' | 'warning' | 'success' | 'danger' }
> = {
  pending: { label: '待執行', variant: 'default' },
  running: { label: '執行中', variant: 'warning' },
  completed: { label: '已完成', variant: 'success' },
  decomposed: { label: '已拆解', variant: 'default' },
  failed: { label: '失敗', variant: 'danger' },
};

function TaskItem({ task }: { task: ParsedTask }) {
  const [open, setOpen] = useState(false);
  const st = STATUS_LABEL[task.status] || STATUS_LABEL.pending;
  const depth = task.depth || 0;

  return (
    <div
      className={cn(
        'rounded-md border border-zinc-200 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-950/60',
      )}
      style={{ marginLeft: depth * 12 }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-zinc-100/80 dark:hover:bg-zinc-900/80"
      >
        <span className="mt-0.5 shrink-0 text-zinc-400">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] text-zinc-400">{task.id}</span>
            <Badge variant={st.variant}>{st.label}</Badge>
            {task.needConfirm && (
              <Badge variant="warning">
                <ShieldAlert size={10} /> 需確認
              </Badge>
            )}
            {task.needThinking && (
              <Badge variant="default">
                <Brain size={10} /> 深思
              </Badge>
            )}
            {task.needDecompose && (
              <Badge variant="default">
                <GitBranch size={10} /> 可拆解
              </Badge>
            )}
            <span className="ml-auto font-mono text-[10px] text-zinc-400">
              信心 {(task.confidence * 100).toFixed(0)}%
            </span>
          </div>
          <div className="text-sm font-medium leading-snug text-zinc-800 dark:text-zinc-100">
            {task.title || '（無標題）'}
          </div>
        </div>
      </button>

      {open && (
        <div className="space-y-2 border-t border-zinc-200 px-3 py-2.5 text-xs dark:border-zinc-800">
          {task.method && (
            <Field label="方法">{task.method}</Field>
          )}
          {task.condition && (
            <Field label="條件">{task.condition}</Field>
          )}
          {task.note && (
            <Field label="注意">{task.note}</Field>
          )}
          {task.result && (
            <Field label="結果">{task.result}</Field>
          )}
          {!task.method && !task.condition && !task.note && !task.result && (
            <span className="text-zinc-400">無詳細欄位</span>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
        {label}
      </div>
      <div className="whitespace-pre-wrap break-words leading-relaxed text-zinc-600 dark:text-zinc-300">
        {children}
      </div>
    </div>
  );
}

type TaskTreeCardProps = {
  markdown: string;
  waitingConfirm?: boolean;
  onConfirmStep?: () => void;
};

export default function TaskTreeCard({ markdown, waitingConfirm, onConfirmStep }: TaskTreeCardProps) {
  const tasks = parseTaskTreeMarkdown(markdown);

  return (
    <div className="my-1 overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
        <ListTree size={14} className="text-zinc-500" />
        <span className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
          任務樹
        </span>
        <span className="text-[11px] text-zinc-400">{tasks.length} 項</span>
      </div>

      <div className="space-y-1.5 p-2.5">
        {tasks.length === 0 ? (
          <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md bg-zinc-50 p-2 font-mono text-[11px] text-zinc-600 dark:bg-zinc-950 dark:text-zinc-400">
            {markdown}
          </pre>
        ) : (
          tasks.map((t) => <TaskItem key={t.id} task={t} />)
        )}
      </div>

      {waitingConfirm && onConfirmStep && (
        <div className="border-t border-zinc-200 px-3 py-2.5 dark:border-zinc-800">
          <Button variant="primary" size="sm" onClick={onConfirmStep}>
            <CheckCircle2 size={14} />
            確認執行此步驟
          </Button>
        </div>
      )}
    </div>
  );
}
