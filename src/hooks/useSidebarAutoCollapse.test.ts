import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useSidebarAutoCollapse } from "./useSidebarAutoCollapse";

function setWindowWidth(width: number) {
	Object.defineProperty(window, "innerWidth", {
		writable: true,
		configurable: true,
		value: width,
	});
}

function fireResize() {
	act(() => {
		window.dispatchEvent(new Event("resize"));
	});
}

describe("useSidebarAutoCollapse", () => {
	afterEach(() => {
		setWindowWidth(1024);
	});

	it("視窗夠寬時初始不收合", () => {
		setWindowWidth(1200);
		const { result } = renderHook(() => useSidebarAutoCollapse());
		expect(result.current.collapsed).toBe(false);
	});

	it("視窗一開始就很窄時初始就收合", () => {
		setWindowWidth(500);
		const { result } = renderHook(() => useSidebarAutoCollapse());
		expect(result.current.collapsed).toBe(true);
	});

	it("視窗變窄會自動收合，變寬會自動展開", () => {
		setWindowWidth(1200);
		const { result } = renderHook(() => useSidebarAutoCollapse());
		expect(result.current.collapsed).toBe(false);

		setWindowWidth(500);
		fireResize();
		expect(result.current.collapsed).toBe(true);

		setWindowWidth(1200);
		fireResize();
		expect(result.current.collapsed).toBe(false);
	});

	it("使用者手動收合後，視窗變窄再變寬不會被自動展開", () => {
		setWindowWidth(1200);
		const { result } = renderHook(() => useSidebarAutoCollapse());

		act(() => {
			result.current.setCollapsedByUser(true);
		});
		expect(result.current.collapsed).toBe(true);

		setWindowWidth(500);
		fireResize();
		expect(result.current.collapsed).toBe(true);

		setWindowWidth(1200);
		fireResize();
		expect(result.current.collapsed).toBe(true); // 使用者的偏好應該被尊重，不會被自動展開蓋掉
	});

	it("使用者手動展開後，視窗維持寬的狀態下應該保持展開", () => {
		setWindowWidth(500); // 一開始自動收合
		const { result } = renderHook(() => useSidebarAutoCollapse());
		expect(result.current.collapsed).toBe(true);

		setWindowWidth(1200);
		fireResize(); // 變寬 -> 自動展開
		expect(result.current.collapsed).toBe(false);

		act(() => {
			result.current.setCollapsedByUser(false);
		});
		expect(result.current.collapsed).toBe(false);
	});
});
