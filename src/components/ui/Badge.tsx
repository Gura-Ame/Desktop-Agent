import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type BadgeVariant = "success" | "danger" | "warning" | "default";

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
	variant?: BadgeVariant;
};

export function Badge({
	className,
	variant = "default",
	...props
}: BadgeProps) {
	return (
		<span
			className={cn(
				"inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium border",
				variant === "success" &&
					"bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400",
				variant === "danger" &&
					"bg-rose-500/10 text-rose-700 border-rose-500/20 dark:text-rose-400",
				variant === "warning" &&
					"bg-amber-500/10 text-amber-700 border-amber-500/20 dark:text-amber-400",
				variant === "default" &&
					"bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700",
				className,
			)}
			{...props}
		/>
	);
}
