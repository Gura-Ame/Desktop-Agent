/**
 * 解析 Task Tree Markdown DSL → 結構化任務列表（給 UI 用）
 */
export function parseTaskTreeMarkdown(text) {
  if (!text || typeof text !== 'string') return [];

  const cleaned = text
    .replace(/```(?:markdown|text)?/g, '')
    .replace(/【當前任務樹狀態.*?】/g, '')
    .replace(/^#+\s*.*$/gm, '')
    .trim();

  const blocks = cleaned.split(/\n(?=[ \t]*- \[.\])/);
  const tasks = [];

  for (const block of blocks) {
    if (!block.trim()) continue;

    const header = block.match(/- \[(.)\] \[?(TASK-[\d.]+|[\d.]+)?\]?\s*(.*)/);
    if (!header) continue;

    const icon = header[1];
    const id = header[2] || `TASK-${tasks.length + 1}`;
    const title = (header[3] || '').split('\n')[0].trim();

    const field = (name) => {
      const m = block.match(new RegExp(`${name}\\s*[:：]\\s*(.*)`, 'i'));
      return m ? m[1].trim() : '';
    };

    const yes = (s) => /YES|TRUE|是/i.test(s);

    let status = 'pending';
    if (icon.toLowerCase() === 'x') status = 'completed';
    else if (icon === '▾' || icon === '▼') status = 'decomposed';
    else if (icon === '~' || icon === '…' || icon === '➜' || icon === '>') status = 'running';

    const thinkStr = field('深度思考');
    const decomposeStr = field('需要拆解');
    const confirmStr = field('需要確認');
    const confStr = field('信心值');
    let confidence = parseFloat(confStr);
    if (Number.isNaN(confidence)) confidence = 0.85;

    tasks.push({
      id,
      title,
      status,
      method: field('方法'),
      condition: field('條件'),
      note: field('注意'),
      result: field('結果'),
      needThinking: yes(thinkStr),
      needDecompose: yes(decomposeStr),
      needConfirm: confirmStr ? yes(confirmStr) : true,
      confidence,
    });
  }

  return tasks;
}
