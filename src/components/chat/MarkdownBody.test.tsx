import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MarkdownBody from "./MarkdownBody";

describe("MarkdownBody", () => {
	it("renders basic markdown without crashing", () => {
		render(<MarkdownBody content="**粗體**\n\n- 第一項\n- 第二項" />);
		expect(screen.getByText("粗體")).toBeInTheDocument();
		expect(screen.getByText("第一項")).toBeInTheDocument();
		expect(screen.getByText("第二項")).toBeInTheDocument();
	});

	it("renders inline math", () => {
		render(<MarkdownBody content="答案是 $x^2$。" />);
		expect(document.querySelector(".katex")).toBeTruthy();
	});

	it("renders fenced code", () => {
		render(<MarkdownBody content={'```ts\nconst answer = 42;\n```'} />);
		expect(screen.getByText("const answer = 42;")).toBeInTheDocument();
	});
});
