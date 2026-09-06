import { AlertTriangle, Check, Info, X } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "../../lib/utils";

export type ToastKind = "success" | "error" | "warning" | "info";

export type ToastItem = {
	id: string;
	kind: ToastKind;
	message: string;
	durationMs?: number;
};

type ToastHostProps = {
	toasts: ToastItem[];
	onDismiss: (id: string) => void;
};

const KIND_STYLE: Record<
	ToastKind,
	{ iconWrap: string; bar: string; Icon: typeof Check; glow: string }
> = {
	success: {
		iconWrap:
			"text-emerald-600 bg-emerald-500/15 ring-1 ring-emerald-500/20 dark:text-emerald-400",
		bar: "bg-emerald-500",
		Icon: Check,
		glow: "shadow-emerald-500/15",
	},
	error: {
		iconWrap:
			"text-rose-600 bg-rose-500/15 ring-1 ring-rose-500/20 dark:text-rose-400",
		bar: "bg-rose-500",
		Icon: X,
		glow: "shadow-rose-500/15",
	},
	warning: {
		iconWrap:
			"text-amber-600 bg-amber-500/15 ring-1 ring-amber-500/20 dark:text-amber-400",
		bar: "bg-amber-500",
		Icon: AlertTriangle,
		glow: "shadow-amber-500/15",
	},
	info: {
		iconWrap:
			"text-sky-600 bg-sky-500/15 ring-1 ring-sky-500/20 dark:text-sky-400",
		bar: "bg-sky-500",
		Icon: Info,
		glow: "shadow-sky-500/15",
	},
};

function ToastCard({
	toast,
	onDismiss,
}: {
	toast: ToastItem;
	onDismiss: (id: string) => void;
}) {
	const { iconWrap, bar, Icon, glow } = KIND_STYLE[toast.kind];
	const duration = toast.durationMs ?? 4200;
	const [leaving, setLeaving] = useState(false);

	const dismiss = () => {
		if (leaving) return;
		setLeaving(true);
		window.setTimeout(() => onDismiss(toast.id), 220);
	};

	useEffect(() => {
		const t = window.setTimeout(dismiss, duration);
		return () => window.clearTimeout(t);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [toast.id, duration]);

	return (
		<div
			role="alert"
			className={cn(
				"pointer-events-auto relative overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl",
				"border-zinc-200/70 bg-white/90 text-zinc-800",
				"dark:border-zinc-700/70 dark:bg-zinc-900/90 dark:text-zinc-100",
				glow,
				leaving
					? "animate-[toast-out_0.22s_ease-in_forwards]"
					: "animate-[toast-in_0.35s_cubic-bezier(0.22,1,0.36,1)]",
			)}
		>
			<div className="flex w-full max-w-sm items-start gap-3 p-3.5 pr-2">
				<div
					className={cn(
						"inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl",
						iconWrap,
					)}
				>
					<Icon size={16} strokeWidth={2.25} />
				</div>
				<div className="min-w-0 flex-1 pt-1 text-sm leading-snug break-words">
					{toast.message}
				</div>
				<button
					type="button"
					aria-label="關閉"
					onClick={dismiss}
					className="ms-auto flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-zinc-400 transition-all duration-150 hover:bg-zinc-100 hover:text-zinc-700 active:scale-95 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
				>
					<X size={15} />
				</button>
			</div>
			{/* 倒數進度條 */}
			<div className="h-0.5 w-full bg-zinc-100 dark:bg-zinc-800">
				<div
					className={cn("h-full origin-left rounded-full", bar)}
					style={{
						animation: `toast-progress ${duration}ms linear forwards`,
					}}
				/>
			</div>
		</div>
	);
}

/** 右上角堆疊 toast */
export function ToastHost({ toasts, onDismiss }: ToastHostProps) {
	if (toasts.length === 0) return null;
	return (
		<div className="pointer-events-none fixed right-4 top-4 z-[200] flex w-[min(100vw-2rem,24rem)] flex-col gap-2.5">
			{toasts.map((t) => (
				<ToastCard key={t.id} toast={t} onDismiss={onDismiss} />
			))}
		</div>
	);
}
