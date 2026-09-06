import { useCallback, useEffect, useRef, useState } from "react";

/** 視窗寬度低於此值時自動收合側欄 */
const SIDEBAR_AUTO_COLLAPSE_PX = 900;

/**
 * 側欄「窄視窗自動收合、放大後自動展開，除非使用者自己手動收合過」的邏輯。
 * 從 App.tsx 拆出來——這一整塊（state + 兩個 ref + resize listener）跟其他
 * App 層級的狀態完全無關，是可以獨立驗證、獨立閱讀的一個小單元。
 */
export function useSidebarAutoCollapse() {
	const [collapsed, setCollapsed] = useState(
		() =>
			typeof window !== "undefined" &&
			window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX,
	);

	// 使用者手動收合時記住，放大視窗後不要擅自展開
	const userPreferCollapsedRef = useRef(false);
	// 是否因視窗過窄而自動收合（放大後可自動展開，除非使用者偏好收合）
	const autoCollapsedRef = useRef(
		typeof window !== "undefined" &&
			window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX,
	);

	useEffect(() => {
		const onResize = () => {
			const narrow = window.innerWidth < SIDEBAR_AUTO_COLLAPSE_PX;
			if (narrow) {
				autoCollapsedRef.current = true;
				setCollapsed(true);
			} else if (autoCollapsedRef.current && !userPreferCollapsedRef.current) {
				autoCollapsedRef.current = false;
				setCollapsed(false);
			}
		};
		window.addEventListener("resize", onResize);
		return () => window.removeEventListener("resize", onResize);
	}, []);

	const setCollapsedByUser = useCallback((next: boolean) => {
		userPreferCollapsedRef.current = next;
		autoCollapsedRef.current = false;
		setCollapsed(next);
	}, []);

	return { collapsed, setCollapsedByUser };
}
