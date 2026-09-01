/**
 * parseTaskTree.js 的測試。
 * 執行方式：node test_parseTaskTree.mjs
 */

import assert from "node:assert";
import { parseTaskTreeMarkdown } from "./parseTaskTree.js";

function test_header_line_does_not_eat_first_task() {
	// 這是最嚴重的一個 bug：標題行後面緊接著的第一個任務，過去會被 header 清除的正則式一起吃掉。
	const sample =
		"### 【當前任務樹狀態 (Task Tree)】\n" +
		"- [ ] [TASK-1] 第一個任務\n" +
		"  - 方法: 做點什麼\n" +
		"  - 條件: 做完了\n" +
		"  - 注意: 無\n" +
		"  - 深度思考: NO\n" +
		"  - 需要拆解: NO\n" +
		"  - 需要確認: NO\n" +
		"  - 信心值: 0.9\n";

	const tasks = parseTaskTreeMarkdown(sample);
	assert.strictEqual(
		tasks.length,
		1,
		`應該解析出 1 個任務，實際: ${tasks.length}`,
	);
	assert.strictEqual(tasks[0].id, "TASK-1");
	assert.strictEqual(tasks[0].title, "第一個任務");
	console.log("[PASS] test_header_line_does_not_eat_first_task");
}

function test_parses_alphanumeric_dotted_id() {
	const sample =
		"- [x] [TASK-1.impact1] 檢查 route_request 是否受影響\n" +
		"  - 結果: 已確認相容\n";
	const tasks = parseTaskTreeMarkdown(sample);
	assert.strictEqual(tasks.length, 1);
	assert.strictEqual(tasks[0].id, "TASK-1.impact1", "id 裡有字母不該被切斷");
	assert.strictEqual(tasks[0].title, "檢查 route_request 是否受影響");
	assert.strictEqual(tasks[0].status, "completed");
	console.log("[PASS] test_parses_alphanumeric_dotted_id");
}

function test_title_starting_with_bracket_not_misparsed_as_id() {
	const sample =
		"- [ ] [TASK-1] [重要] 做某事\n" +
		"  - 方法: 做某事的方法\n" +
		"  - 條件: 做完了\n" +
		"  - 注意: 無\n" +
		"  - 深度思考: NO\n" +
		"  - 需要拆解: NO\n" +
		"  - 需要確認: NO\n" +
		"  - 信心值: 0.9\n";
	const tasks = parseTaskTreeMarkdown(sample);
	assert.strictEqual(tasks[0].id, "TASK-1");
	assert.strictEqual(tasks[0].title, "[重要] 做某事");
	console.log("[PASS] test_title_starting_with_bracket_not_misparsed_as_id");
}

function test_depth_reflects_real_indentation_not_dot_count_in_id() {
	// 拆解出來的子任務有真的縮排 -> depth 應該是 1。
	// code_impact 產生的影響檢查任務結構上沒有 parent_id、後端不會縮排它，
	// 即使 id 裡有點，也不該被誤判成有縮排。
	const sample =
		"- [x] [TASK-1] 修改 handle_login 函式\n" +
		"  - 結果: 已完成修改\n" +
		"- [x] [TASK-1.impact1] 檢查 route_request 是否受影響\n" +
		"  - 結果: 已確認相容\n" +
		"- [▾] [TASK-2] 整理桌面資料夾\n" +
		"  - (已拆解為 1 個子任務，見下方)\n" +
		"  - [ ] [TASK-2.1] 建立分類資料夾\n" +
		"    - 方法: mkdir docs\n" +
		"    - 條件: 資料夾存在\n" +
		"    - 注意: 無\n" +
		"    - 深度思考: NO\n" +
		"    - 需要拆解: NO\n" +
		"    - 需要確認: NO\n" +
		"    - 信心值: 0.9\n";

	const tasks = parseTaskTreeMarkdown(sample);
	const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));

	assert.strictEqual(byId["TASK-1"].depth, 0);
	assert.strictEqual(
		byId["TASK-1.impact1"].depth,
		0,
		"impact-check 任務結構上是獨立任務，不該被縮排",
	);
	assert.strictEqual(byId["TASK-2"].depth, 0);
	assert.strictEqual(
		byId["TASK-2.1"].depth,
		1,
		"真正的拆解子任務應該要縮排一層",
	);
	console.log(
		"[PASS] test_depth_reflects_real_indentation_not_dot_count_in_id",
	);
}

function test_decomposed_and_running_status_icons() {
	const sample =
		"- [▾] [TASK-1] 已拆解的容器任務\n" +
		"  - (已拆解為 1 個子任務，見下方)\n" +
		"  - [➜] [TASK-1.1] 正在執行的子任務\n" +
		"    - 方法: 做點什麼\n" +
		"    - 條件: 做完了\n" +
		"    - 注意: 無\n" +
		"    - 深度思考: NO\n" +
		"    - 需要拆解: NO\n" +
		"    - 需要確認: NO\n" +
		"    - 信心值: 0.9\n";
	const tasks = parseTaskTreeMarkdown(sample);
	const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
	assert.strictEqual(byId["TASK-1"].status, "decomposed");
	assert.strictEqual(byId["TASK-1.1"].status, "running");
	console.log("[PASS] test_decomposed_and_running_status_icons");
}

function test_empty_input_returns_empty_array() {
	assert.deepStrictEqual(parseTaskTreeMarkdown(""), []);
	assert.deepStrictEqual(parseTaskTreeMarkdown(null), []);
	assert.deepStrictEqual(parseTaskTreeMarkdown(undefined), []);
	console.log("[PASS] test_empty_input_returns_empty_array");
}

const tests = [
	test_header_line_does_not_eat_first_task,
	test_parses_alphanumeric_dotted_id,
	test_title_starting_with_bracket_not_misparsed_as_id,
	test_depth_reflects_real_indentation_not_dot_count_in_id,
	test_decomposed_and_running_status_icons,
	test_empty_input_returns_empty_array,
];

for (const t of tests) t();
console.log(`\n全部 ${tests.length} 個測試通過。`);
