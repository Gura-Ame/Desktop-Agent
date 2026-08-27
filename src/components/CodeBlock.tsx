import { Check, Copy } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { cn } from '../lib/utils';

/**
 * 語法高亮程式碼區塊。
 * 優先用 highlight.js（若已安裝）；否則純文字 + 基本關鍵字著色。
 */
function fallbackHighlight(code: string) {
  const escaped = code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 極簡著色：字串 / 註解 / 數字
  return escaped
    .replace(
      /(\/\/.*$|#.*$)/gm,
      '<span class="hl-comment">$1</span>',
    )
    .replace(
      /(&quot;|&#39;|")(?:(?!\1)[^\\]|\\.)*\1|'(?:[^'\\]|\\.)*'/g,
      '<span class="hl-string">$&</span>',
    )
    .replace(
      /\b(def|class|return|if|else|elif|for|while|import|from|as|try|except|with|async|await|const|let|var|function|return|true|false|null|None|True|False)\b/g,
      '<span class="hl-keyword">$1</span>',
    )
    .replace(
      /\b(\d+\.?\d*)\b/g,
      '<span class="hl-number">$1</span>',
    );
}

type CodeBlockProps = {
  code: string | string[] | unknown;
  language?: string;
};

export default function CodeBlock({ code, language }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [html, setHtml] = useState<string | null>(null);
  const lang = (language || '').replace(/^language-/, '') || 'text';

  const plain = useMemo(() => {
    if (typeof code === 'string') return code.replace(/\n$/, '');
    if (Array.isArray(code)) return code.join('').replace(/\n$/, '');
    return String(code ?? '').replace(/\n$/, '');
  }, [code]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const hljs = (await import('highlight.js/lib/core')).default;
        // 常用語言按需註冊
        const langs: Record<string, () => Promise<{ default: (hljsApi: typeof hljs) => unknown }>> = {
          python: () => import('highlight.js/lib/languages/python'),
          py: () => import('highlight.js/lib/languages/python'),
          javascript: () => import('highlight.js/lib/languages/javascript'),
          js: () => import('highlight.js/lib/languages/javascript'),
          typescript: () => import('highlight.js/lib/languages/typescript'),
          ts: () => import('highlight.js/lib/languages/typescript'),
          bash: () => import('highlight.js/lib/languages/bash'),
          shell: () => import('highlight.js/lib/languages/bash'),
          json: () => import('highlight.js/lib/languages/json'),
          sql: () => import('highlight.js/lib/languages/sql'),
          cpp: () => import('highlight.js/lib/languages/cpp'),
          c: () => import('highlight.js/lib/languages/c'),
          java: () => import('highlight.js/lib/languages/java'),
          rust: () => import('highlight.js/lib/languages/rust'),
          go: () => import('highlight.js/lib/languages/go'),
          html: () => import('highlight.js/lib/languages/xml'),
          xml: () => import('highlight.js/lib/languages/xml'),
          css: () => import('highlight.js/lib/languages/css'),
          markdown: () => import('highlight.js/lib/languages/markdown'),
          md: () => import('highlight.js/lib/languages/markdown'),
        };
        const loader = langs[lang.toLowerCase()];
        if (loader && !hljs.getLanguage(lang.toLowerCase())) {
          const mod = await loader();
          hljs.registerLanguage(lang.toLowerCase(), mod.default as Parameters<typeof hljs.registerLanguage>[1]);
        }
        if (cancelled) return;
        if (hljs.getLanguage(lang.toLowerCase())) {
          setHtml(hljs.highlight(plain, { language: lang.toLowerCase() }).value);
        } else {
          setHtml(hljs.highlightAuto(plain).value);
        }
      } catch {
        if (!cancelled) setHtml(fallbackHighlight(plain));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [plain, lang]);

  const onCopy = async () => {
    try {
      if (window.pywebview?.api?.copy_to_clipboard) {
        await window.pywebview.api.copy_to_clipboard(plain);
      } else {
        await navigator.clipboard.writeText(plain);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="group/code my-2 overflow-hidden rounded-md border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-200 px-3 py-1 dark:border-zinc-800">
        <span className="font-mono text-[10px] uppercase tracking-wide text-zinc-400">
          {lang}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className="rounded p-1 text-zinc-400 opacity-0 transition-opacity hover:text-zinc-700 group-hover/code:opacity-100 dark:hover:text-zinc-200"
          title="複製程式碼"
        >
          {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
        </button>
      </div>
      <pre
        className={cn(
          'code-block overflow-x-auto p-3 font-mono text-[12px] leading-relaxed',
          'text-zinc-800 dark:text-zinc-200',
        )}
      >
        {html ? (
          <code dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code>{plain}</code>
        )}
      </pre>
    </div>
  );
}
