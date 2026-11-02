/** Confirmation for destructive actions: states exactly what goes and that it cannot be undone. */
import { useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export function ConfirmDelete({ title, children, pending, onConfirm, onClose }: {
  title: string;
  children: ReactNode;
  pending: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  return (
    <Dialog open onOpenChange={(o) => !o && !pending && onClose()}>
      <DialogContent onOpenAutoFocus={(event) => { event.preventDefault(); cancel.current?.focus(); }}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-2">
              {children}
              <p className="font-medium text-fg-1">此操作不能撤销。</p>
            </div>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button ref={cancel} variant="outline" onClick={onClose} disabled={pending}>取消</Button>
          <Button variant="destructive" onClick={onConfirm} disabled={pending}>{pending ? "正在删除…" : "删除"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
