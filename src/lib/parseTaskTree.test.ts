import { describe, expect, it } from "vitest";
import { parseTaskTreeMarkdown } from "./parseTaskTree";

describe("parseTaskTreeMarkdown", () => {
	it("回傳空陣列給沒有內容的輸入", () => {
		expect(parseTaskTreeMarkdown(undefined)).toEqual([]);
		expect(parseTaskTreeMarkdown(null)).toEqual([]);
		expect(parseTaskTreeMarkdown("")).toEqual([]);
	});

	it("解析基本欄位（id/title/status/confidence）", () => {
		const md = `
- [ ] [TASK-1] 澄清使用者意圖
  - 方法: 詢問使用者
  - 條件: 使用者回覆明確關鍵字
  - 注意: 無
  - 需要確認: NO
  - 信心值: 0.85
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks).toHaveLength(1);
		expect(tasks[0]).toMatchObject({
			id: "TASK-1",
			title: "澄清使用者意圖",
			status: "pending",
			method: "詢問使用者",
			condition: "使用者回覆明確關鍵字",
			needConfirm: false,
			confidence: 0.85,
		});
	});

	it("[x] 對應 completed 狀態，need_confirm 沒標明時保守視為 YES", () => {
		const md = `
- [x] [TASK-1] 已完成的任務
  - 結果: 做完了
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks[0].status).toBe("completed");
		// 後端 task_system.py 對應的預設也是保守當作需要確認（見 TaskNode.need_confirm 預設 True）。
		expect(tasks[0].needConfirm).toBe(true);
	});

	it("依縮排空白（不是 id 裡的點）計算 depth", () => {
		const md = `
- [ ] [TASK-1] 父任務
  - 需要確認: NO
  - [ ] [TASK-1.1] 子任務
    - 需要確認: NO
`;
		const tasks = parseTaskTreeMarkdown(md);
		const parent = tasks.find((t) => t.id === "TASK-1");
		const child = tasks.find((t) => t.id === "TASK-1.1");
		expect(parent?.depth).toBe(0);
		expect(child?.depth).toBeGreaterThan(parent?.depth ?? 0);
	});

	it("忽略 markdown code fence 與狀態標題雜訊", () => {
		const md = `
\`\`\`markdown
【當前任務樹狀態】
- [ ] [TASK-1] 標題
  - 需要確認: NO
\`\`\`
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks).toHaveLength(1);
		expect(tasks[0].id).toBe("TASK-1");
	});

	// 以下幾個案例是從舊的手寫腳本 `test_parseTaskTree.mjs`（用 node assert、
	// 手動 `node test_parseTaskTree.mjs` 執行，沒有真的整合進任何測試指令）搬過來的，
	// 涵蓋幾個過去真的修過的具體 bug，改用 .ts 原始碼直接測、跟著 `npm run test` 一起跑。

	it("標題行後面緊接著的第一個任務不該被 header 清除的正則式一起吃掉", () => {
		const md = `### 【當前任務樹狀態 (Task Tree)】
- [ ] [TASK-1] 第一個任務
  - 方法: 做點什麼
  - 條件: 做完了
  - 注意: 無
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks).toHaveLength(1);
		expect(tasks[0].id).toBe("TASK-1");
		expect(tasks[0].title).toBe("第一個任務");
	});

	it("id 裡有英文字母的 dotted id（如 impact 檢查任務）不該被切斷", () => {
		const md = `- [x] [TASK-1.impact1] 檢查 route_request 是否受影響
  - 結果: 已確認相容
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks).toHaveLength(1);
		expect(tasks[0].id).toBe("TASK-1.impact1");
		expect(tasks[0].title).toBe("檢查 route_request 是否受影響");
		expect(tasks[0].status).toBe("completed");
	});

	it("標題本身以中括號開頭時不該被誤判成 id 的一部分", () => {
		const md = `- [ ] [TASK-1] [重要] 做某事
  - 方法: 做某事的方法
  - 條件: 做完了
  - 需要確認: NO
  - 信心值: 0.9
`;
		const tasks = parseTaskTreeMarkdown(md);
		expect(tasks[0].id).toBe("TASK-1");
		expect(tasks[0].title).toBe("[重要] 做某事");
	});

	it("depth 該反映真正的縮排，不是 id 裡有幾個點", () => {
		// code_impact 產生的「影響檢查」任務結構上沒有 parent_id、不會被縮排，
		// 即使 id 裡有點（TASK-1.impact1）也不該被誤判成有縮排。
		const md = `- [x] [TASK-1] 修改 handle_login 函式
  - 結果: 已完成修改
- [x] [TASK-1.impact1] 檢查 route_request 是否受影響
  - 結果: 已確認相容
- [▾] [TASK-2] 整理桌面資料夾
  - (已拆解為 1 個子任務，見下方)
  - [ ] [TASK-2.1] 建立分類資料夾
    - 方法: mkdir docs
    - 條件: 資料夾存在
    - 需要確認: NO
    - 信心值: 0.9
`;
		const tasks = parseTaskTreeMarkdown(md);
		const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
		expect(byId["TASK-1"].depth).toBe(0);
		expect(byId["TASK-1.impact1"].depth).toBe(0);
		expect(byId["TASK-2"].depth).toBe(0);
		expect(byId["TASK-2.1"].depth).toBe(1);
	});

	it("[▾] 對應 decomposed、[➜] 對應 running", () => {
		const md = `- [▾] [TASK-1] 已拆解的容器任務
  - (已拆解為 1 個子任務，見下方)
  - [➜] [TASK-1.1] 正在執行的子任務
    - 方法: 做點什麼
    - 條件: 做完了
    - 需要確認: NO
    - 信心值: 0.9
`;
		const tasks = parseTaskTreeMarkdown(md);
		const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
		expect(byId["TASK-1"].status).toBe("decomposed");
		expect(byId["TASK-1.1"].status).toBe("running");
	});
});
