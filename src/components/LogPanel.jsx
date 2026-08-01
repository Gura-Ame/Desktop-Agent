import { Terminal, X } from 'lucide-react';
import { Button } from './ui/Button';

export default function LogPanel({ logs, onClose }) {
  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-zinc-200 bg-white font-mono text-xs dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-200 px-3 py-2.5 font-sans text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        <span className="flex items-center gap-2">
          <Terminal size={14} />
          系統日誌
        </span>
        <Button variant="ghost" size="icon" onClick={onClose} title="關閉">
          <X size={14} />
        </Button>
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto p-3 leading-relaxed text-zinc-500 selection:bg-zinc-200 dark:text-zinc-400 dark:selection:bg-zinc-800">
        {logs.length === 0 ? (
          <span className="text-zinc-400 dark:text-zinc-600">暫無 Log…</span>
        ) : (
          logs.map((log, i) => (
            <div
              key={i}
              className="whitespace-pre-wrap break-all border-b border-zinc-100 pb-1.5 last:border-0 dark:border-zinc-800/50"
            >
              {log}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
