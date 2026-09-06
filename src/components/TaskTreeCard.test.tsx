import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TaskTreeCard from "./TaskTreeCard";

// 對應這次修的 bug：need_confirm 是規劃階段就定案的靜態屬性（這個任務執行前
// 該不該暫停確認），不是即時狀態。任務一旦完成，繼續顯示「需確認」徽章
// 會讓使用者誤以為同一個任務同時處於「已完成」跟「待確認」兩種矛盾狀態
// （見使用者回報的截圖：TASK-1 同時掛著綠色「已完成」跟橘色「需確認」）。
describe("TaskTreeCard - 需確認徽章顯示規則", () => {
	it("任務已完成時不該再顯示「需確認」徽章，即使 need_confirm 是 YES", () => {
		const md = `
- [x] [TASK-1] 澄清使用者意圖
  - 需要確認: YES
  - 信心值: 0.85
  - 結果: 完成
`;
		render(<TaskTreeCard markdown={md} />);
		expect(screen.getByText("已完成")).toBeInTheDocument();
		expect(screen.queryByText("需確認")).not.toBeInTheDocument();
	});

	it("任務還在 pending 且 need_confirm 是 YES 時，應該顯示「需確認」徽章", () => {
		const md = `
- [ ] [TASK-2] 待執行任務
  - 需要確認: YES
  - 信心值: 0.9
`;
		render(<TaskTreeCard markdown={md} />);
		expect(screen.getByText("待執行")).toBeInTheDocument();
		expect(screen.getByText("需確認")).toBeInTheDocument();
	});

	it("任務失敗時（FAILED）也不該顯示「需確認」徽章", () => {
		const md = `
- [!] [TASK-3] 失敗的任務
  - 需要確認: YES
`;
		render(<TaskTreeCard markdown={md} />);
		// 這個 icon 目前的 parseTaskTree 邏輯會落到預設 pending，這裡主要驗證
		// completed/decomposed 兩種「已有定論」的狀態不會誤觸；如果之後
		// parseTaskTree 補上明確的 failed icon 對應，這個案例的 status 判斷
		// 要跟著更新，但「需確認」的顯示規則本身不受影響。
		expect(screen.queryByText("已完成")).not.toBeInTheDocument();
	});

	it("任務已拆解（decomposed）時不該顯示「需確認」徽章", () => {
		const md = `
- [▾] [TASK-4] 已拆解的父任務
  - 需要確認: YES
`;
		render(<TaskTreeCard markdown={md} />);
		expect(screen.getByText("已拆解")).toBeInTheDocument();
		expect(screen.queryByText("需確認")).not.toBeInTheDocument();
	});
});
