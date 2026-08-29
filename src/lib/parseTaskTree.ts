import type { ParsedTask, TaskStatus } from "../types";

/**
 * 解析 Task Tree Markdown DSL → 結構化任務列表（給 UI 用）
 */
export function parseTaskTreeMarkdown(
	text: string | undefined | null,
): ParsedTask[] {
	if (!text || typeof text !== "string") return [];

	const cleaned = text
		.replace(/```(?:markdown|text)?/g, "")
		.replace(/【當前任務樹狀態.*?】/g, "")
		.replace(/^#+.*$/gm, "")
		.trim();

	const blocks = cleaned.split(/\n(?=[ \t]*- \[.\])/);
	const tasks: ParsedTask[] = [];

	for (const block of blocks) {
		if (!block.trim()) continue;

		// id 允許英數字/底線/點/連字號組成的任意識別字（例如 "TASK-1"、"TASK-1.1"、
		// "TASK-1.impact1"，跟後端 task_system.py 用同一套規則），限制字元集合是為了
		// 避免誤把「[重要] 做某事」這種標題本身就用中括號開頭的一般文字，誤判成任務 id。
		const header = block.match(
			/- \[(.)\]\s*(?:\[([A-Za-z0-9_.\-]+)\])?\s*(.*)/,
		);
		if (!header) continue;

		const icon = header[1];
		const id = header[2] || `TASK-${tasks.length + 1}`;
		const title = (header[3] || "").split("\n")[0].trim();

		// 縮排讀實際的前導空白，不是用 id 裡有幾個點去猜——
		// 後端渲染的縮排是根據真正的 parent_id 關係算出來的（例如自動插入的影響檢查任務
		// 結構上是獨立任務、沒有 parent_id，即使 id 裡有點也不會被後端縮排），
		// 只有讀實際字元才能跟後端的資料結構保持一致。Python 那邊每一層縮排是 2 個空白。
		const leadingWhitespace = block.match(/^[ \t]*/)?.[0] ?? "";
		const depth = Math.floor(leadingWhitespace.length / 2);

		const field = (name: string) => {
			const m = block.match(new RegExp(`${name}\\s*[:：]\\s*(.*)`, "i"));
			return m ? m[1].trim() : "";
		};

		const yes = (s: string) => /YES|TRUE|是/i.test(s);

		let status: TaskStatus = "pending";
		if (icon.toLowerCase() === "x") status = "completed";
		else if (icon === "▾" || icon === "▼") status = "decomposed";
		else if (icon === "~" || icon === "…" || icon === "➜" || icon === ">")
			status = "running";

		const thinkStr = field("深度思考");
		const decomposeStr = field("需要拆解");
		const confirmStr = field("需要確認");
		const confStr = field("信心值");
		let confidence = parseFloat(confStr);
		if (Number.isNaN(confidence)) confidence = 0.85;

		tasks.push({
			id,
			title,
			status,
			depth,
			method: field("方法"),
			condition: field("條件"),
			note: field("注意"),
			result: field("結果"),
			needThinking: yes(thinkStr),
			needDecompose: yes(decomposeStr),
			needConfirm: confirmStr ? yes(confirmStr) : true,
			confidence,
		});
	}

	return tasks;
}
