import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatInput from "./ChatInput";

describe("ChatInput", () => {
	const baseProps = {
		value: "",
		onChange: vi.fn(),
		onSend: vi.fn(),
		onStop: vi.fn(),
		waitingUserInput: null,
		isBusy: false,
	};

	it("Enter 會送出，Shift+Enter 不會送出", () => {
		const onSend = vi.fn();
		render(<ChatInput {...baseProps} onSend={onSend} />);
		const textarea = screen.getByPlaceholderText(/輸入指令或問題/);

		fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
		expect(onSend).toHaveBeenCalledTimes(1);

		fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
		expect(onSend).toHaveBeenCalledTimes(1);
	});

	it("忙碌時顯示停止按鈕並可停止 Agent", () => {
		const onStop = vi.fn();
		render(<ChatInput {...baseProps} isBusy onStop={onStop} />);
		fireEvent.click(screen.getByTitle("停止 Agent"));
		expect(onStop).toHaveBeenCalledTimes(1);
	});

	it("有等待中的使用者問題時顯示提問內容", () => {
		render(
			<ChatInput
				{...baseProps}
				waitingUserInput="請問要使用哪一個檔案？"
			/>,
		);
		expect(screen.getByText("Agent 提問（請在下方回答）")).toBeInTheDocument();
		expect(screen.getByText("請問要使用哪一個檔案？")).toBeInTheDocument();
	});

	it("有附加檔案時可以移除檔案", () => {
		const onRemoveFile = vi.fn();
		render(
			<ChatInput
				{...baseProps}
				files={[{ id: "file-1", name: "notes.txt", path: "C:/notes.txt" }]}
				onRemoveFile={onRemoveFile}
			/>,
		);
		expect(screen.getByText("notes.txt")).toBeInTheDocument();
		fireEvent.click(screen.getByTitle("移除"));
		expect(onRemoveFile).toHaveBeenCalledWith("file-1");
	});
});
