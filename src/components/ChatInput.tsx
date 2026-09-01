import { ImagePlus, Send, Square, X } from "lucide-react";
import type { ChangeEvent, CSSProperties, KeyboardEvent } from "react";
import { useRef } from "react";
import type { ChatImage } from "../types";
import { Button } from "./ui/Button";

type ChatInputProps = {
	value: string;
	onChange: (value: string) => void;
	onSend: () => void;
	onStop: () => void;
	waitingUserInput: string | null;
	isBusy: boolean;
	images?: ChatImage[];
	onAddImages?: (list: ChatImage[]) => void;
	onRemoveImage?: (id: string) => void;
};

export default function ChatInput({
	value,
	onChange,
	onSend,
	onStop,
	waitingUserInput,
	isBusy,
	images = [],
	onAddImages,
	onRemoveImage,
}: ChatInputProps) {
	const fileRef = useRef<HTMLInputElement>(null);

	const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			if (!isBusy) onSend();
		}
	};

	const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
		const files = Array.from(e.target.files || []);
		e.target.value = "";
		if (!files.length || !onAddImages) return;

		const readers = files
			.filter((f) => f.type.startsWith("image/"))
			.map(
				(f) =>
					new Promise<ChatImage>((resolve) => {
						const reader = new FileReader();
						reader.onload = () => {
							resolve({
								id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
								name: f.name,
								mime: f.type,
								dataUrl: String(reader.result ?? ""),
							});
						};
						reader.readAsDataURL(f);
					}),
			);

		Promise.all(readers).then((list) => {
			if (list.length) onAddImages(list);
		});
	};

	return (
		<div className="shrink-0 border-t border-zinc-300 bg-[#e0e0e2]/90 px-4 py-3 backdrop-blur dark:border-[#3a3a3c] dark:bg-[#242426]/95">
			<div className="mx-auto max-w-3xl space-y-2">
				{waitingUserInput && (
					<div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-400">
						<span className="mt-1.5 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-amber-500" />
						<div className="min-w-0 flex-1 space-y-0.5">
							<div className="font-medium text-amber-900 dark:text-amber-300">
								Agent 提問（請在下方回答）
							</div>
							<div className="max-h-28 overflow-y-auto whitespace-pre-wrap break-words leading-relaxed text-amber-800/90 dark:text-amber-400/90">
								{waitingUserInput}
							</div>
						</div>
					</div>
				)}

				{images.length > 0 && (
					<div className="flex flex-wrap gap-2">
						{images.map((img) => (
							<div
								key={img.id}
								className="group relative h-16 w-16 overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700"
							>
								<img
									src={img.dataUrl}
									alt={img.name}
									className="h-full w-full object-cover"
								/>
								<button
									type="button"
									onClick={() => onRemoveImage?.(img.id)}
									className="absolute right-0.5 top-0.5 rounded bg-black/60 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100"
									title="移除"
								>
									<X size={12} />
								</button>
							</div>
						))}
					</div>
				)}

				<div className="flex items-end gap-2 rounded-md border border-zinc-200 bg-white px-2 py-1.5 shadow-sm focus-within:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:focus-within:border-zinc-600">
					<input
						ref={fileRef}
						type="file"
						accept="image/*"
						multiple
						className="hidden"
						onChange={onFileChange}
					/>
					<Button
						variant="ghost"
						size="icon"
						className="mb-0.5 shrink-0"
						onClick={() => fileRef.current?.click()}
						title="上傳圖片"
						disabled={isBusy && !waitingUserInput}
					>
						<ImagePlus size={16} />
					</Button>

					<textarea
						value={value}
						onChange={(e) => onChange(e.target.value)}
						onKeyDown={onKeyDown}
						rows={1}
						placeholder={
							waitingUserInput
								? "請輸入回答…（Enter 送出，Shift+Enter 換行）"
								: "輸入指令或問題…（Enter 送出，Shift+Enter 換行）"
						}
						className="max-h-36 min-h-[36px] flex-1 resize-none bg-transparent px-1 py-1.5 text-sm leading-5 text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-100 dark:placeholder:text-zinc-500"
						style={{ fieldSizing: "content" } as CSSProperties}
					/>

					{isBusy ? (
						<Button
							variant="destructive"
							size="icon"
							className="mb-0.5 shrink-0"
							onClick={onStop}
							title="停止 Agent"
						>
							<Square size={14} className="fill-current" />
						</Button>
					) : (
						<Button
							variant="default"
							size="icon"
							className="mb-0.5 shrink-0"
							onClick={onSend}
							disabled={!value.trim() && images.length === 0}
							title="送出"
						>
							<Send size={14} />
						</Button>
					)}
				</div>
			</div>
		</div>
	);
}
