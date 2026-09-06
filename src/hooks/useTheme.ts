import { useCallback, useEffect, useState } from "react";
import type { Theme } from "../types";

const STORAGE_KEY = "desktop-agent-theme";

function getInitialTheme(): Theme {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved === "light" || saved === "dark") return saved;
	} catch {
		/* ignore */
	}
	if (typeof window !== "undefined" && window.matchMedia) {
		return window.matchMedia("(prefers-color-scheme: light)").matches
			? "light"
			: "dark";
	}
	return "dark";
}

function applyTheme(theme: Theme, withTransition: boolean) {
	const root = document.documentElement;
	if (withTransition) {
		root.classList.add("theme-animating");
		window.setTimeout(() => {
			root.classList.remove("theme-animating");
		}, 400);
	}
	if (theme === "dark") {
		root.classList.add("dark");
	} else {
		root.classList.remove("dark");
	}
}

/**
 * 深淺色模式，持久化到 localStorage；切換時加上短暫 transition class。
 */
export function useTheme() {
	const [theme, setThemeState] = useState<Theme>(getInitialTheme);

	useEffect(() => {
		// 初次掛載不播動畫，避免整頁閃一下
		applyTheme(theme, false);
		try {
			localStorage.setItem(STORAGE_KEY, theme);
		} catch {
			/* ignore */
		}
	}, []);

	const setTheme = useCallback((next: Theme) => {
		const t = next === "light" ? "light" : "dark";
		applyTheme(t, true);
		setThemeState(t);
		try {
			localStorage.setItem(STORAGE_KEY, t);
		} catch {
			/* ignore */
		}
	}, []);

	const toggleTheme = useCallback(() => {
		setThemeState((prev) => {
			const next = prev === "dark" ? "light" : "dark";
			applyTheme(next, true);
			try {
				localStorage.setItem(STORAGE_KEY, next);
			} catch {
				/* ignore */
			}
			return next;
		});
	}, []);

	return { theme, setTheme, toggleTheme, isDark: theme === "dark" };
}
