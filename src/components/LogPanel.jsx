import { Terminal } from 'lucide-react';

export default function LogPanel({ logs, onClose }) {
    return (
        <aside className="w-96 bg-zinc-900 border-l border-zinc-800 flex flex-col font-mono text-xs shrink-0">
            <div className="p-3 bg-zinc-950 border-b border-zinc-800 flex justify-between items-center text-zinc-400 font-sans text-xs">
                <span className="flex items-center gap-2">
                    <Terminal size={14} /> 系統日誌
                </span>
                <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
            </div>
            <div className="flex-1 p-3 overflow-y-auto space-y-1.5 text-zinc-400 leading-relaxed selection:bg-zinc-800">
                {logs.length === 0 ? (
                    <span className="text-zinc-600">暫無 Log 紀錄...</span>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="whitespace-pre-wrap break-all border-b border-zinc-800/40 pb-1">
                            {log}
                        </div>
                    ))
                )}
            </div>
        </aside>
    );
}