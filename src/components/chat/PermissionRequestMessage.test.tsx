import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PermissionInfo } from "../../types";
import PermissionRequestMessage from "./PermissionRequestMessage";

const info: PermissionInfo = {
	tool: "execute_python",
	args: "'print(1)'",
	risk: "dangerous",
};

describe("PermissionRequestMessage", () => {
	it("顯示工具名稱、參數跟風險等級，並提供三個決定按鈕", () => {
		render(<PermissionRequestMessage info={info} onRespond={() => {}} />);
		expect(screen.getByText("execute_python")).toBeInTheDocument();
		expect(screen.getByText(/print\(1\)/)).toBeInTheDocument();
		expect(screen.getByText("高風險")).toBeInTheDocument();
		expect(screen.getByText(/允許這一次/)).toBeInTheDocument();
		expect(screen.getByText(/本次工作階段永久允許/)).toBeInTheDocument();
		expect(screen.getByText(/拒絕/)).toBeInTheDocument();
	});

	it("點擊按鈕會用正確的 decision 字串呼叫 onRespond", () => {
		const onRespond = vi.fn();
		render(<PermissionRequestMessage info={info} onRespond={onRespond} />);
		fireEvent.click(screen.getByText(/本次工作階段永久允許/));
		expect(onRespond).toHaveBeenCalledWith("allow_session");
	});

	it("resolved 有值時不再顯示按鈕，改顯示已解決的結果", () => {
		render(
			<PermissionRequestMessage
				info={info}
				resolved="deny"
				onRespond={() => {}}
			/>,
		);
		expect(screen.queryByText(/允許這一次/)).not.toBeInTheDocument();
		expect(screen.getByText("已拒絕")).toBeInTheDocument();
	});
});
