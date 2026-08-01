import { Bot, Check, CheckCircle2, Copy, User } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { parseMessageContent } from '../lib/parseMessage';
import { cn } from '../lib/utils';
import { Button } from './ui/Button';
import ToolCallBlock from './ToolCallBlock';

const markdownComponents = {
  code({ className, children, ...props }) {
    if (className?.includes('language-math') || className?.includes('math')) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="break-all rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-xs text-emerald-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-emerald-400"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre({ children, ...props }) {
    return (
      <pre
        className="my-2 overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300"
        {...props}
      >
        {children}
      </pre>
    );
  },
  p({ children }) {
    return <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>;
  },
  ul({ children }) {
    return <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>;
  },
  li({ children }) {
    return <li className="leading-relaxed">{children}</li>;
  },
  strong({ children }) {
    return (
      <strong className="font-semibold text-zinc-900 dark:text-zinc-50">{children}</strong>
    );
  },
};

/** 複製用：去掉 tool_call 標記，保留可讀文字 */
function plainTextForCopy(content) {
  if (!content) return '';
  return content
    .replace(/<\|tool_call\|>[\s\S]*?(?:<\/?\|?tool_call\|?>|$)/g, '')
    .replace(/<\/?tool_result>/g, '')
    .replace(/<\/?tool_error>/g, '')
    .trim();
}

export default function ChatMessage({
  msg,
  isLast,
  waitingConfirm,
  onConfirmStep,
  onCopy,
}) {
  const blocks = parseMessageContent(msg.content);
  const isUser = msg.role === 'user';
  const [copied, setCopied] = useState(false);

  const handleCopyClick = async () => {
    const text = plainTextForCopy(msg.content);
    if (!text || !onCopy) return;
    await onCopy(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className={cn(
        'group mx-auto flex max-w-3xl min-w-0 gap-3',
        isUser ? 'justify-end' : 'justify-start',
      )}
    >
      {!isUser && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <Bot size={14} />
        </div>
      )}

      <div
        className={cn(
          'relative chat-selectable min-w-0 max-w-[min(85%,42rem)] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'rounded-br-sm bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-950'
            : 'rounded-bl-sm border border-zinc-200 bg-white text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-200',
        )}
      >
        {/* Agent 訊息：複製按鈕 */}
        {!isUser && !msg.isStreaming && msg.content && (
          <button
            type="button"
            onClick={handleCopyClick}
            title={copied ? '已複製' : '複製內容'}
            className={cn(
              'absolute right-2 top-2 rounded-md p-1.5 transition-all',
              'text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700',
              'dark:hover:bg-zinc-800 dark:hover:text-zinc-200',
              'opacity-0 focus:opacity-100 group-hover:opacity-100',
              copied && 'opacity-100 text-emerald-600 dark:text-emerald-400',
            )}
          >
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
        )}

        <div
          className={cn(
            'chat-selectable min-w-0 space-y-1.5 overflow-x-auto break-words',
            !isUser && 'pr-7',
          )}
        >
          {blocks.map((block, idx) => {
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
                components={markdownComponents}
              >
                {block.content}
              </ReactMarkdown>
            );
          })}

          {msg.isStreaming && (
            <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-zinc-400 align-middle dark:bg-zinc-500" />
          )}
        </div>

        {msg.isTree && waitingConfirm && isLast && (
          <Button variant="primary" size="sm" className="mt-3" onClick={onConfirmStep}>
            <CheckCircle2 size={14} />
            確認執行此步驟
          </Button>
        )}
      </div>

      {isUser && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
          <User size={14} />
        </div>
      )}
    </div>
  );
}
