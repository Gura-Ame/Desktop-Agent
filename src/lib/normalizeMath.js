/**
 * 把常見數學分隔符統一成 remark-math / KaTeX 吃得下的 $ / $$。
 * 模型常輸出 \(...\)、\[...\]，或把 $ 寫成 \$。
 */
export function normalizeMathDelimiters(text) {
  if (!text || typeof text !== 'string') return text;

  let s = text;

  // 保護已存在的 code fence，避免動到程式碼裡的反斜線
  const fences = [];
  s = s.replace(/```[\s\S]*?```/g, (m) => {
    fences.push(m);
    return `\u0000FENCE${fences.length - 1}\u0000`;
  });

  // \[ ... \] → $$ ... $$
  s = s.replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => `\n$$\n${body.trim()}\n$$\n`);

  // \( ... \) → $ ... $
  s = s.replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => `$${body.trim()}$`);

  // 保底：某些模型不寫 \[ \] / \( \)，直接用裸的 [ ... ] 包公式（常見於較弱的本地模型）。
  // 這種寫法在一般文字（備註、markdown 連結 [text](url)、[TODO] 之類）裡也很常見，
  // 所以要盡量保守：必須有 LaTeX 指令（\frac、\sqrt...）、上下標（^、_{），
  // 或「字母 空格 運算符 空格 字母/數字」這種明顯是算式排版的樣子（要求運算符兩側都有空白，
  // 避免誤傷「bug-123」「a-to-z」這類一般連字號用法），且後面不能緊跟 '(' （避免誤傷 markdown 連結）。
  const looksLikeMath = (body) =>
    /\\[a-zA-Z]+|\^|_\{|[a-zA-Z0-9]\s+[-+*/=]\s+[a-zA-Z0-9]/.test(body);
  s = s.replace(/\[([^\[\]\n]{1,200})\](?!\()/g, (m, body) => {
    if (!looksLikeMath(body)) return m;
    return `$${body.trim()}$`;
  });

  // 行內孤立的 a^2、b^2 若已在 $ 內就不動；其餘保持原文

  // 還原 code fence
  s = s.replace(/\u0000FENCE(\d+)\u0000/g, (_, i) => fences[Number(i)]);

  return s;
}
