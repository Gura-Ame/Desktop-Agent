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

  // 行內孤立的 a^2、b^2 若已在 $ 內就不動；其餘保持原文

  // 還原 code fence
  s = s.replace(/\u0000FENCE(\d+)\u0000/g, (_, i) => fences[Number(i)]);

  return s;
}
