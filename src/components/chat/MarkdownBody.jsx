import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { normalizeMathDelimiters } from '../../lib/normalizeMath';
import CodeBlock from '../CodeBlock';
import MathPreview from '../MathPreview';

/** 從 children 抽出純文字 */
function childText(children) {
  if (children == null) return '';
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map(childText).join('');
  if (children.props?.children) return childText(children.props.children);
  return '';
}

const markdownComponents = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    const isInline = !match && !String(children).includes('\n');

    // KaTeX / math
    if (className?.includes('language-math') || className?.includes('math')) {
      const raw = childText(children).replace(/\n$/, '');
      const display = className?.includes('math-display');
      return <MathPreview source={raw} display={display} />;
    }

    // 區塊程式碼 → 高亮
    if (!isInline) {
      return <CodeBlock code={childText(children)} language={match?.[1]} />;
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
  pre({ children }) {
    return <>{children}</>;
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

export default function MarkdownBody({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: 'ignore' }]]}
      components={markdownComponents}
    >
      {normalizeMathDelimiters(content)}
    </ReactMarkdown>
  );
}
