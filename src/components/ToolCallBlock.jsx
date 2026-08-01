import { CheckCircle2, ChevronDown, ChevronRight, Code2, XCircle } from 'lucide-react';
import { useState } from 'react';

export default function ToolCallBlock({ funcName, args, result }) {
    const [isOpen, setIsOpen] = useState(false);
    const isError = result ? (result.includes("錯誤") || result.includes("失敗")) : false;
    const isDone = result !== null && result !== undefined;

    return (
        <div className="my-2 rounded-xl border border-zinc-800 bg-zinc-950/80 font-mono text-xs overflow-hidden shadow-sm">
            <div
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center justify-between px-3 py-2 bg-zinc-900/90 cursor-pointer hover:bg-zinc-900 transition-colors select-none"
            >
                <div className="flex items-center gap-2 min-w-0 pr-2">
                    <Code2 size={14} className="text-emerald-400 shrink-0" />
                    <span className="font-semibold text-zinc-200">{funcName}</span>
                    <span className="text-zinc-500 truncate text-[11px]">
                        ({args ? (args.length > 30 ? `${args.slice(0, 30)}...` : args) : ''})
                    </span>
                </div>

                <div className="flex items-center gap-2 shrink-0 font-sans text-[11px]">
                    {isDone ? (
                        isError ? (
                            <span className="flex items-center gap-1 text-rose-400">
                                <XCircle size={13} /> 失敗
                            </span>
                        ) : (
                            <span className="flex items-center gap-1 text-emerald-400">
                                <CheckCircle2 size={13} /> 成功
                            </span>
                        )
                    ) : (
                        <span className="text-amber-400 animate-pulse">執行中...</span>
                    )}
                    {isOpen ? <ChevronDown size={14} className="text-zinc-400" /> : <ChevronRight size={14} className="text-zinc-400" />}
                </div>
            </div>

            {isOpen && (
                <div className="p-3 border-t border-zinc-800/80 space-y-2 bg-zinc-950/40">
                    <div>
                        <div className="text-[10px] text-zinc-500 font-sans font-medium uppercase mb-1">參數 (Input)</div>
                        <pre className="p-2 rounded-lg bg-zinc-900 text-zinc-300 overflow-x-auto whitespace-pre-wrap break-all border border-zinc-800/60">
                            {args || '(無參數)'}
                        </pre>
                    </div>

                    {result && (
                        <div>
                            <div className="text-[10px] text-zinc-500 font-sans font-medium uppercase mb-1">輸出 (Output)</div>
                            <pre className={`p-2 rounded-lg overflow-x-auto whitespace-pre-wrap break-all border ${isError
                                    ? 'bg-rose-950/20 text-rose-300 border-rose-900/30'
                                    : 'bg-zinc-900 text-emerald-400 border-zinc-800/60'
                                }`}>
                                {result}
                            </pre>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}