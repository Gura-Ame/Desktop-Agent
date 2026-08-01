import { Bot, CheckCircle2, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkMath from 'remark-math';
import ToolCallBlock from './ToolCallBlock';

function parseMessageContent(content) {
    if (!content) return [];

    const blocks = [];
    let cursor = 0;

    while (cursor < content.length) {
        const toolCallStart = content.indexOf('<|tool_call|>', cursor);

        if (toolCallStart === -1) {
            const restText = content.slice(cursor);
            if (restText) blocks.push({ type: 'text', content: restText });
            break;
        }

        if (toolCallStart > cursor) {
            const textBefore = content.slice(cursor, toolCallStart);
            if (textBefore) blocks.push({ type: 'text', content: textBefore });
        }

        const afterHeader = content.slice(toolCallStart + 13);
        const callMatch = afterHeader.match(/^\s*call:(\w+)\(/);

        if (!callMatch) {
            blocks.push({
                type: 'tool',
                funcName: '載入中...',
                args: '',
                result: null
            });
            break;
        }

        const funcName = callMatch[1];
        const argsStartIdx = toolCallStart + 13 + callMatch[0].length;
        const closeMatch = content.slice(argsStartIdx).match(/<\/?\|?tool_call\|?>/);

        if (!closeMatch) {
            // 正在 Streaming 參數，去掉末尾多餘的右括號
            let currentArgs = content.slice(argsStartIdx).trim();
            if (currentArgs.endsWith(')')) currentArgs = currentArgs.slice(0, -1).trim();

            blocks.push({
                type: 'tool',
                funcName,
                args: currentArgs,
                result: null
            });
            break;
        }

        const argsEndRelativeIdx = closeMatch.index;
        let rawArgs = content.slice(argsStartIdx, argsStartIdx + argsEndRelativeIdx).trim();

        // 剔除末尾屬於 call(...) 的閉合右括號
        if (rawArgs.endsWith(')')) {
            rawArgs = rawArgs.slice(0, -1).trim();
        }

        const toolCallEndIdx = argsStartIdx + argsEndRelativeIdx + closeMatch[0].length;
        const afterToolCall = content.slice(toolCallEndIdx);
        const resultStartMatch = afterToolCall.match(/^\s*<(tool_result|tool_error)>/);

        if (!resultStartMatch) {
            blocks.push({
                type: 'tool',
                funcName,
                args: rawArgs,
                result: null
            });
            cursor = toolCallEndIdx;
            continue;
        }

        const resultType = resultStartMatch[1];
        const resContentStartIdx = toolCallEndIdx + resultStartMatch[0].length;
        const closeResultTag = `</${resultType}>`;
        const resultEndIdx = content.indexOf(closeResultTag, resContentStartIdx);

        if (resultEndIdx === -1) {
            const currentResult = content.slice(resContentStartIdx).trim();
            blocks.push({
                type: 'tool',
                funcName,
                args: rawArgs,
                result: resultType === 'tool_error' ? `錯誤: ${currentResult}` : currentResult
            });
            break;
        }

        const rawResult = content.slice(resContentStartIdx, resultEndIdx).trim();
        blocks.push({
            type: 'tool',
            funcName,
            args: rawArgs,
            result: resultType === 'tool_error' ? `錯誤: ${rawResult}` : rawResult
        });

        cursor = resultEndIdx + closeResultTag.length;
    }

    return blocks;
}

export default function ChatMessage({ msg, isLast, waitingConfirm, onConfirmStep }) {
    const parsedBlocks = parseMessageContent(msg.content);

    return (
        <div className={`flex gap-3 max-w-4xl mx-auto min-w-0 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'agent' && (
                <div className="w-8 h-8 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center shrink-0 text-emerald-400 mt-0.5">
                    <Bot size={16} />
                </div>
            )}

            <div className={`chat-selectable min-w-0 max-w-[85%] rounded-2xl p-4 text-sm leading-relaxed shadow-sm ${msg.role === 'user'
                ? 'bg-emerald-600 text-white rounded-br-none font-medium'
                : 'bg-zinc-900 border border-zinc-800/80 text-zinc-200 rounded-bl-none'
                }`}>
                <div className="chat-selectable overflow-x-auto min-w-0 break-words space-y-2">
                    {parsedBlocks.map((block, idx) => {
                        if (block.type === 'tool') {
                            return (
                                <ToolCallBlock
                                    key={idx}
                                    funcName={block.funcName}
                                    args={block.args}
                                    result={block.result}
                                />
                            );
                        }

                        return (
                            <ReactMarkdown
                                key={idx}
                                remarkPlugins={[remarkMath]}
                                rehypePlugins={[rehypeKatex]}
                                components={{
                                    code({ node, inline, className, children, ...props }) {
                                        // KaTeX 已處理的數學不要再包一層 code 樣式
                                        if (className?.includes('language-math') || className?.includes('math')) {
                                            return <code className={className} {...props}>{children}</code>;
                                        }
                                        return (
                                            <code className="bg-zinc-950 text-emerald-400 px-1.5 py-0.5 rounded font-mono text-xs border border-zinc-800 break-all" {...props}>
                                                {children}
                                            </code>
                                        );
                                    },
                                    pre({ node, children, ...props }) {
                                        return (
                                            <pre className="bg-zinc-950 text-zinc-300 p-3 rounded-lg border border-zinc-800/80 font-mono text-xs overflow-x-auto whitespace-pre-wrap break-all my-2 shadow-inner" {...props}>
                                                {children}
                                            </pre>
                                        );
                                    }
                                }}
                            >
                                {block.content}
                            </ReactMarkdown>
                        );
                    })}
                </div>

                {msg.isTree && waitingConfirm && isLast && (
                    <button
                        onClick={onConfirmStep}
                        className="mt-3 flex items-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold px-4 py-2 rounded-lg text-xs shadow transition-all active:scale-[0.98]"
                    >
                        <CheckCircle2 size={16} /> 確認執行此步驟
                    </button>
                )}
            </div>

            {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0 text-emerald-400 mt-0.5">
                    <User size={16} />
                </div>
            )}
        </div>
    );
}