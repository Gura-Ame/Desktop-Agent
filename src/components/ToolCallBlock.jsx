import { CheckCircle2, ChevronDown, ChevronRight, Code2, XCircle } from 'lucide-react';
import { useState } from 'react';
import { cn } from '../lib/utils';
import { Badge } from './ui/Badge';

export default function ToolCallBlock({ funcName, args, result }) {
  const [open, setOpen] = useState(false);
  const isError =
    result != null && (String(result).includes('錯誤') || String(result).includes('失敗'));
  const isDone = result !== null && result !== undefined;

  return (
    <div className="my-2 overflow-hidden rounded-md border border-zinc-200 bg-zinc-50 font-mono text-xs dark:border-zinc-800 dark:bg-zinc-950/80">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full select-none items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-900"
      >
        <div className="flex min-w-0 items-center gap-2">
          <Code2 size={13} className="shrink-0 text-zinc-400 dark:text-zinc-500" />
          <span className="font-medium text-zinc-800 dark:text-zinc-200">{funcName}</span>
          <span className="truncate text-[11px] text-zinc-400 dark:text-zinc-500">
            ({args ? (args.length > 36 ? `${args.slice(0, 36)}…` : args) : ''})
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2 font-sans">
          {isDone ? (
            isError ? (
              <Badge variant="danger">
                <XCircle size={11} /> 失敗
              </Badge>
            ) : (
              <Badge variant="success">
                <CheckCircle2 size={11} /> 成功
              </Badge>
            )
          ) : (
            <Badge variant="warning">執行中…</Badge>
          )}
          {open ? (
            <ChevronDown size={14} className="text-zinc-400" />
          ) : (
            <ChevronRight size={14} className="text-zinc-400" />
          )}
        </div>
      </button>

      {open && (
        <div className="space-y-2 border-t border-zinc-200 px-3 py-2.5 dark:border-zinc-800">
          <div>
            <div className="mb-1 font-sans text-[10px] font-medium uppercase tracking-wide text-zinc-400">
              Input
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-zinc-200 bg-white p-2 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
              {args || '(無參數)'}
            </pre>
          </div>

          {result != null && (
            <div>
              <div className="mb-1 font-sans text-[10px] font-medium uppercase tracking-wide text-zinc-400">
                Output
              </div>
              <pre
                className={cn(
                  'overflow-x-auto whitespace-pre-wrap break-all rounded-md border p-2',
                  isError
                    ? 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300'
                    : 'border-zinc-200 bg-white text-emerald-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-emerald-400',
                )}
              >
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
