import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ToggleFeatureCard from "./ToggleFeatureCard";

describe("ToggleFeatureCard", () => {
	it("開啟時顯示開啟說明，點擊後切換為關閉", () => {
		const onToggle = vi.fn();
		render(
			<ToggleFeatureCard
				icon={null}
				label="測試功能"
				enabled
				onToggle={onToggle}
				enabledDescription="目前已開啟"
				disabledDescription="目前已關閉"
			/>,
		);
		expect(screen.getByText("目前已開啟")).toBeInTheDocument();
		const toggle = screen.getByRole("switch");
		expect(toggle).toHaveAttribute("aria-checked", "true");
		fireEvent.click(toggle);
		expect(onToggle).toHaveBeenCalledWith(false);
	});
});
