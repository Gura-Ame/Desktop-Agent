/**
 * 把 agent 回覆拆成 text / tool 區塊。
 * 支援 <|tool_call|>call:fn(...)<|tool_call|> 與後續 <tool_result> / <tool_error>
 */
export function parseMessageContent(content) {
  if (!content) return [];

  const blocks = [];
  let cursor = 0;

  while (cursor < content.length) {
    const toolCallStart = content.indexOf('<|tool_call|>', cursor);

    if (toolCallStart === -1) {
      const rest = content.slice(cursor);
      if (rest) blocks.push({ type: 'text', content: rest });
      break;
    }

    if (toolCallStart > cursor) {
      const textBefore = content.slice(cursor, toolCallStart);
      if (textBefore) blocks.push({ type: 'text', content: textBefore });
    }

    const afterHeader = content.slice(toolCallStart + 13);
    const callMatch = afterHeader.match(/^\s*call:(\w+)\(/);

    if (!callMatch) {
      blocks.push({ type: 'tool', funcName: '載入中...', args: '', result: null });
      break;
    }

    const funcName = callMatch[1];
    const argsStartIdx = toolCallStart + 13 + callMatch[0].length;
    const closeMatch = content.slice(argsStartIdx).match(/<\/?\|?tool_call\|?>/);

    if (!closeMatch) {
      let currentArgs = content.slice(argsStartIdx).trim();
      if (currentArgs.endsWith(')')) currentArgs = currentArgs.slice(0, -1).trim();
      blocks.push({ type: 'tool', funcName, args: currentArgs, result: null });
      break;
    }

    const argsEndRelativeIdx = closeMatch.index;
    let rawArgs = content.slice(argsStartIdx, argsStartIdx + argsEndRelativeIdx).trim();
    if (rawArgs.endsWith(')')) rawArgs = rawArgs.slice(0, -1).trim();

    const toolCallEndIdx = argsStartIdx + argsEndRelativeIdx + closeMatch[0].length;
    const afterToolCall = content.slice(toolCallEndIdx);
    const resultStartMatch = afterToolCall.match(/^\s*<(tool_result|tool_error)>/);

    if (!resultStartMatch) {
      blocks.push({ type: 'tool', funcName, args: rawArgs, result: null });
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
        result: resultType === 'tool_error' ? `錯誤: ${currentResult}` : currentResult,
      });
      break;
    }

    const rawResult = content.slice(resContentStartIdx, resultEndIdx).trim();
    blocks.push({
      type: 'tool',
      funcName,
      args: rawArgs,
      result: resultType === 'tool_error' ? `錯誤: ${rawResult}` : rawResult,
    });

    cursor = resultEndIdx + closeResultTag.length;
  }

  return blocks;
}
