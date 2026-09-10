import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Sidebar from "./SideBar";

const props = {
	isCollapsed: false,
	setIsCollapsed: vi.fn(),
	clientMode: "local_llama" as const,
	setClientMode: vi.fn(),
	baseUrl: "http://localhost:8000",
	setBaseUrl: vi.fn(),
	apiKey: "",
	setApiKey: vi.fn(),
	modelName: "test",
	setModelName: vi.fn(),
	modelPath: "C:/model.gguf",
	setModelPath: vi.fn(),
	applyApiConfig: vi.fn(),
	serverStatus: { running: true, msg: "ok" },
	checkServerHealth: vi.fn(),
	executionMode: "SMART" as const,
	handleModeChange: vi.fn(),
	clearDrawings: vi.fn(),
	clearHistory: vi.fn(),
	showLogWindow: false,
	setShowLogWindow: vi.fn(),
	forgettingEnabled: true,
	handleForgettingToggle: vi.fn(),
	activationEnabled: true,
	handleActivationToggle: vi.fn(),
	thinkingEnabled: false,
	handleThinkingToggle: vi.fn(),
	instantInputEnabled: false,
	handleInstantInputToggle: vi.fn(),
	permissionMode: "ask" as const,
	handlePermissionModeChange: vi.fn(),
};

describe("Sidebar", () => {
	it("展開時顯示執行模式與權限策略", () => {
		render(<Sidebar {...props} />);
		expect(screen.getByText("Task Tree 執行模式")).toBeInTheDocument();
		expect(screen.getByText("工具授權策略")).toBeInTheDocument();
	});

	it("收合時仍保留展開控制與執行模式提示", () => {
		render(<Sidebar {...props} isCollapsed />);
		expect(screen.getByTitle("展開側邊欄")).toBeInTheDocument();
		expect(screen.getByTitle("執行模式: SMART")).toBeInTheDocument();
	});
});
