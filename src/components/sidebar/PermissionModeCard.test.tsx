import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PermissionModeCard from "./PermissionModeCard";

describe("PermissionModeCard", () => {
	it("顯示目前策略並可切換授權模式", () => {
		const onChange = vi.fn();
		render(<PermissionModeCard permissionMode="ask" handlePermissionModeChange={onChange} />);
		expect(screen.getByText("工具授權策略")).toBeInTheDocument();
		fireEvent.click(screen.getByText("全部信任"));
		expect(onChange).toHaveBeenCalledWith("auto");
	});
});
