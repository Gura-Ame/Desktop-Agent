import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ExecutionModeCard from "./ExecutionModeCard";

describe("ExecutionModeCard", () => {
	it("顯示目前模式說明並可切換模式", () => {
		const onChange = vi.fn();
		render(<ExecutionModeCard executionMode="SMART" handleModeChange={onChange} />);
		expect(screen.getByText("Task Tree 執行模式")).toBeInTheDocument();
		fireEvent.click(screen.getByText("逐步確認"));
		expect(onChange).toHaveBeenCalledWith("STEP_BY_STEP");
	});
});
