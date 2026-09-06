import { useCallback, useState } from "react";
import type { ToastItem, ToastKind } from "../components/ui/Toast";

let toastSeq = 0;

export function useToast() {
	const [toasts, setToasts] = useState<ToastItem[]>([]);

	const dismissToast = useCallback((id: string) => {
		setToasts((prev) => prev.filter((t) => t.id !== id));
	}, []);

	const pushToast = useCallback(
		(kind: ToastKind, message: string, durationMs?: number) => {
			const id = `toast-${++toastSeq}-${Date.now()}`;
			setToasts((prev) => [...prev, { id, kind, message, durationMs }]);
			return id;
		},
		[],
	);

	return { toasts, pushToast, dismissToast };
}
