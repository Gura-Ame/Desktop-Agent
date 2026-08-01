import { Send } from 'lucide-react';
import { Button } from './ui/Button';

export default function ChatInput({
  value,
  onChange,
  onSend,
  waitingUserInput,
}) {
  return (
    <div className="shrink-0 border-t border-zinc-200 bg-zinc-50/90 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90">
      <div className="mx-auto max-w-3xl space-y-2">
        {waitingUserInput && (
          <div className="flex items-center gap-2 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
            <span className="truncate">Agent 提問：{waitingUserInput}</span>
          </div>
        )}

        <div className="flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-2 py-1 shadow-sm focus-within:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:focus-within:border-zinc-600">
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && onSend()}
            placeholder={waitingUserInput ? '請輸入回答…' : '輸入指令或問題…'}
            className="h-9 flex-1 bg-transparent px-2 text-sm text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-100 dark:placeholder:text-zinc-500"
          />
          <Button
            variant="default"
            size="icon"
            onClick={onSend}
            disabled={!value.trim()}
            title="送出"
          >
            <Send size={14} />
          </Button>
        </div>
      </div>
    </div>
  );
}
