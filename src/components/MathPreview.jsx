import { useEffect, useState } from 'react';
import { normalizeMathDelimiters } from '../lib/normalizeMath';

/**
 * 將 $...$ / $$...$$ / \(...\) 渲染成 KaTeX HTML 預覽。
 */
export default function MathPreview({ source, display = false }) {
  const [html, setHtml] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const katex = (await import('katex')).default;
        const raw = normalizeMathDelimiters(source || '')
          .replace(/^\$+|\$+$/g, '')
          .replace(/^\\\(|\\\)$/g, '')
          .replace(/^\\\[|\\\]$/g, '')
          .trim();
        const out = katex.renderToString(raw, {
          throwOnError: false,
          displayMode: display,
          strict: 'ignore',
        });
        if (!cancelled) setHtml(out);
      } catch {
        if (!cancelled) setHtml(source);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, display]);

  if (!html) return <span className="font-mono text-xs text-zinc-400">{source}</span>;

  return (
    <span
      className={display ? 'my-2 block overflow-x-auto' : 'mx-0.5 inline-block'}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
