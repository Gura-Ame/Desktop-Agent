type ToggleFeatureCardProps = {
	icon: React.ReactNode;
	label: string;
	enabled: boolean;
	onToggle: (enabled: boolean) => void;
	enabledDescription: string;
	disabledDescription: string;
};

/**
 * 漸進式遺忘卡片跟 Activation 卡片除了圖示/文字之外，結構完全一樣
 * （標題 + 開關 + 一段依開關狀態變化的說明文字），抽成一個共用元件，
 * 之後要再加新的開關型設定卡片，直接重用這個就好，不用每次複製貼上。
 */
export default function ToggleFeatureCard({
	icon,
	label,
	enabled,
	onToggle,
	enabledDescription,
	disabledDescription,
}: ToggleFeatureCardProps) {
	return (
		<div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3.5 space-y-2 shadow-sm">
			<div className="flex items-center justify-between">
				<span className="flex items-center gap-1.5 text-xs font-medium text-zinc-400">
					{icon} {label}
				</span>
				<button
					onClick={() => onToggle(!enabled)}
					role="switch"
					aria-checked={enabled}
					title={enabled ? "點擊關閉" : "點擊開啟"}
					className={`relative w-9 h-5 rounded-full transition-colors duration-200 shrink-0 ${
						enabled ? "bg-emerald-500" : "bg-zinc-700"
					}`}
				>
					<span
						className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${
							enabled ? "translate-x-4" : "translate-x-0"
						}`}
					/>
				</button>
			</div>
			<p className="text-[11px] text-zinc-500 leading-relaxed">
				{enabled ? enabledDescription : disabledDescription}
			</p>
		</div>
	);
}
