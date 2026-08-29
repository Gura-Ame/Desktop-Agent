import type { MessageBlock, ToolStatus } from "../types";

/**
 * 把 agent 回覆拆成 text / tool 區塊。
 * 支援 <|tool_call|>fn(...)<|tool_call|> 與後續 <tool_result> / <tool_error>
 *
 * 注意：tool_result 可能中間夾空白/換行；finished 後仍無 result 視為失敗，不要永遠「執行中」。
 */

type ToolResultMatch = {
	resultType: string;
	result: string;
	end: number;
	complete: boolean;
};

function findToolResult(afterToolCall: string): ToolResultMatch | null {
	// 允許 tool_call 結尾與 <tool_result> 之間有空白
	const m = afterToolCall.match(/^\s*<(tool_result|tool_error)>/);
	if (!m || m.index == null) return null;

	const resultType = m[1];
	const contentStart = m.index + m[0].length;
	const closeTag = `</${resultType}>`;
	const closeIdx = afterToolCall.indexOf(closeTag, contentStart);

	if (closeIdx === -1) {
		// 串流中：結果還沒傳完
		return {
			resultType,
			result: afterToolCall.slice(contentStart).trim(),
			end: afterToolCall.length,
			complete: false,
		};
	}

	return {
		resultType,
		result: afterToolCall.slice(contentStart, closeIdx).trim(),
		end: closeIdx + closeTag.length,
		complete: true,
	};
}

export function parseMessageContent(
	content: string | undefined | null,
	opts: { isStreaming?: boolean } = {},
): MessageBlock[] {
	if (!content) return [];

	const isStreaming = !!opts.isStreaming;
	const blocks: MessageBlock[] = [];
	let cursor = 0;

	while (cursor < content.length) {
		const toolCallStart = content.indexOf("<|tool_call|>", cursor);

		if (toolCallStart === -1) {
			const rest = content.slice(cursor);
			// 略過已掛到上一個 tool 的 result 標籤殘段（理論上不會走到）
			if (rest) blocks.push({ type: "text", content: rest });
			break;
		}

		if (toolCallStart > cursor) {
			const textBefore = content.slice(cursor, toolCallStart);
			if (textBefore.trim()) blocks.push({ type: "text", content: textBefore });
		}

		const afterHeader = content.slice(toolCallStart + 13);
		const callMatch = afterHeader.match(/^\s*(\w+)\(/);

		if (!callMatch) {
			blocks.push({
				type: "tool",
				funcName: "…",
				args: "",
				result: isStreaming ? null : "（格式無法解析）",
				status: isStreaming ? "running" : "error",
			});
			break;
		}

		const funcName = callMatch[1];
		const argsStartIdx = toolCallStart + 13 + callMatch[0].length;
		const closeMatch = content
			.slice(argsStartIdx)
			.match(/\)\s*<\/?\|?tool_call\|?>/);

		if (!closeMatch || closeMatch.index == null) {
			// tool_call 尚未串完
			let currentArgs = content.slice(argsStartIdx).trim();
			if (currentArgs.endsWith(")"))
				currentArgs = currentArgs.slice(0, -1).trim();
			blocks.push({
				type: "tool",
				funcName,
				args: currentArgs,
				result: null,
				status: "running",
			});
			break;
		}

		const argsEndRelativeIdx = closeMatch.index;
		const rawArgs = content
			.slice(argsStartIdx, argsStartIdx + argsEndRelativeIdx)
			.trim();
		// closeMatch 已從 ) 開始，args 不含最後的 )
		const toolCallEndIdx =
			argsStartIdx + argsEndRelativeIdx + closeMatch[0].length;

		const afterToolCall = content.slice(toolCallEndIdx);
		const found = findToolResult(afterToolCall);

		if (!found) {
			// 已關閉的 tool_call，但還沒有 result：串流中=執行中；已結束=失敗/無結果
			blocks.push({
				type: "tool",
				funcName,
				args: rawArgs,
				result: isStreaming ? null : "（無回傳結果）",
				status: isStreaming ? "running" : "error",
			});
			cursor = toolCallEndIdx;
			continue;
		}

		const isError =
			found.resultType === "tool_error" ||
			/錯誤|失敗|Exception|Error|Traceback/i.test(found.result || "");

		const status: ToolStatus = !found.complete
			? "running"
			: isError
				? "error"
				: "success";

		blocks.push({
			type: "tool",
			funcName,
			args: rawArgs,
			result:
				found.resultType === "tool_error" &&
				found.result &&
				!found.result.startsWith("錯誤")
					? `錯誤: ${found.result}`
					: found.result,
			status,
		});

		cursor = toolCallEndIdx + found.end;
	}

	return blocks;
}
