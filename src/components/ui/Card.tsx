import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type DivProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, ...props }: DivProps) {
	return (
		<div
			className={cn(
				"rounded-lg border border-zinc-200 bg-white text-zinc-900 shadow-sm",
				"dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-100",
				className,
			)}
			{...props}
		/>
	);
}

export function CardHeader({ className, ...props }: DivProps) {
	return (
		<div
			className={cn(
				"flex items-center justify-between gap-2 px-3.5 pt-3.5 pb-2",
				className,
			)}
			{...props}
		/>
	);
}

export function CardTitle({ className, ...props }: DivProps) {
	return (
		<div
			className={cn(
				"flex items-center gap-1.5 text-xs font-medium text-zinc-500 dark:text-zinc-400",
				className,
			)}
			{...props}
		/>
	);
}

export function CardContent({ className, ...props }: DivProps) {
	return (
		<div className={cn("px-3.5 pb-3.5 space-y-3", className)} {...props} />
	);
}
