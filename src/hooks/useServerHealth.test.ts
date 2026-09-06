import { act, renderHook } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useServerHealth } from "./useServerHealth";

function setup(args: {
	clientMode: "local_llama" | "remote_api";
	baseUrl: string;
	callApi?: (method: string, ...args: unknown[]) => Promise<any>;
}) {
	const setServerStatus = vi.fn();
	const hook = renderHook(() => {
		const isBusyRef = useRef(false);
		const isStreamingRef = useRef(false);
		return useServerHealth({
			...args,
			isBusyRef,
			isStreamingRef,
			setServerStatus,
		});
	});
	return { ...hook, setServerStatus };
}

describe("useServerHealth", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("local_llama 模式若未載入模型回報紅燈未載入，不打 HTTP", async () => {
		const fetchSpy = vi.spyOn(globalThis, "fetch");
		const callApi = vi.fn().mockResolvedValue({ status: "ok", model_loaded: false });
		const { result, setServerStatus } = setup({
			clientMode: "local_llama",
			baseUrl: "http://localhost:12356/v1",
			callApi,
		});
		await act(async () => {
			await result.current.checkServerHealth();
		});
		expect(setServerStatus).toHaveBeenCalledWith({
			running: false,
			msg: "未載入模型",
		});
		expect(fetchSpy).not.toHaveBeenCalled();
	});

	it("local_llama 模式若已成功載入模型回報綠燈並帶模型名", async () => {
		const fetchSpy = vi.spyOn(globalThis, "fetch");
		const callApi = vi.fn().mockResolvedValue({
			status: "ok",
			model_loaded: true,
			model_name: "test-model.gguf",
		});
		const { result, setServerStatus } = setup({
			clientMode: "local_llama",
			baseUrl: "http://localhost:12356/v1",
			callApi,
		});
		await act(async () => {
			await result.current.checkServerHealth();
		});
		expect(setServerStatus).toHaveBeenCalledWith({
			running: true,
			msg: "已載入 (test-model.gguf)",
		});
		expect(fetchSpy).not.toHaveBeenCalled();
	});

	it("remote_api 模式打 /models 成功時回報在線", async () => {
		vi.spyOn(globalThis, "fetch").mockResolvedValue({
			ok: true,
			status: 200,
		} as Response);
		const { result, setServerStatus } = setup({
			clientMode: "remote_api",
			baseUrl: "http://example.com/v1/",
		});
		await act(async () => {
			await result.current.checkServerHealth();
		});
		expect(setServerStatus).toHaveBeenCalledWith({
			running: true,
			msg: "在線",
		});
	});

	it("remote_api 模式 fetch 失敗時回報離線", async () => {
		vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));
		const { result, setServerStatus } = setup({
			clientMode: "remote_api",
			baseUrl: "http://example.com/v1",
		});
		await act(async () => {
			await result.current.checkServerHealth();
		});
		expect(setServerStatus).toHaveBeenCalledWith({
			running: false,
			msg: "離線",
		});
	});

	it("agent 忙碌中時 checkServerHealth 不該發任何請求", async () => {
		const fetchSpy = vi
			.spyOn(globalThis, "fetch")
			.mockResolvedValue({ ok: true, status: 200 } as Response);
		const setServerStatus = vi.fn();
		const { result } = renderHook(() => {
			const isBusyRef = useRef(true); // 一開始就忙碌
			const isStreamingRef = useRef(false);
			return useServerHealth({
				clientMode: "remote_api",
				baseUrl: "http://example.com/v1",
				isBusyRef,
				isStreamingRef,
				setServerStatus,
			});
		});
		await act(async () => {
			await result.current.checkServerHealth();
		});
		expect(fetchSpy).not.toHaveBeenCalled();
		expect(setServerStatus).not.toHaveBeenCalled();
	});
});
