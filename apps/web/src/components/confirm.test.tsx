import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConfirmDelete } from "./confirm";

afterEach(() => {
  cleanup();
  delete window.__POLYMECH_PLATFORM__;
});

it("puts the Windows action on the left while initially focusing Cancel", async () => {
  window.__POLYMECH_PLATFORM__ = "windows";
  render(<ConfirmDelete title="删除合成分析？" pending={false} onConfirm={() => {}} onClose={() => {}}>仅用于测试。</ConfirmDelete>);
  const cancel = screen.getByRole("button", { name: "取消" });
  const remove = screen.getByRole("button", { name: "删除" });
  expect(remove.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(cancel).toHaveFocus();
});

it("keeps the macOS button order", () => {
  window.__POLYMECH_PLATFORM__ = "macos";
  render(<ConfirmDelete title="删除合成分析？" pending={false} onConfirm={() => {}} onClose={() => {}}>仅用于测试。</ConfirmDelete>);
  const cancel = screen.getByRole("button", { name: "取消" });
  const remove = screen.getByRole("button", { name: "删除" });
  expect(cancel.compareDocumentPosition(remove) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
