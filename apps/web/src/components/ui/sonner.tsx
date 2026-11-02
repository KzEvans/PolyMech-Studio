import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useEffect, useState } from "react";

/** Toasts follow the app theme attribute (no next-themes dependency). */
const Toaster = ({ ...props }: ToasterProps) => {
  const [theme, setTheme] = useState<ToasterProps["theme"]>((document.documentElement.dataset.theme as "light" | "dark") ?? "light");
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme((document.documentElement.dataset.theme as "light" | "dark") ?? "light"));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      icons={{
        success: <CircleCheckIcon className="size-4 text-success" />,
        info: <InfoIcon className="size-4 text-info" />,
        warning: <TriangleAlertIcon className="size-4 text-warning" />,
        error: <OctagonXIcon className="size-4 text-danger" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={{ "--normal-bg": "var(--popover)", "--normal-text": "var(--popover-foreground)", "--normal-border": "var(--border)" } as React.CSSProperties}
      {...props}
    />
  );
};

export { Toaster };
