import * as Dialog from "@radix-ui/react-dialog";
import * as Label from "@radix-ui/react-label";
import * as Switch from "@radix-ui/react-switch";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "danger" | "outline" | "ghost";
};

export function Button({ variant = "primary", className, ...props }: ButtonProps) {
  const variants = {
    primary: "bg-[#0f1115] text-white hover:bg-[#30343b] dark:bg-[#f1f2f3] dark:text-[#0f1115] dark:hover:bg-white",
    danger: "bg-[#b72429] text-white hover:bg-[#921d22]",
    outline: "border border-[#aeb3ba] bg-transparent hover:bg-[#ebedef] dark:border-[#626871] dark:hover:bg-[#30343b]",
    ghost: "bg-transparent hover:bg-[#ebedef] dark:hover:bg-[#30343b]",
  };
  return <button className={cn(
    "inline-flex min-h-12 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-bold",
    "transition-colors disabled:cursor-not-allowed disabled:opacity-50", variants[variant], className,
  )} {...props} />;
}

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("surface p-5", className)} {...props} />;
}

export function Field({ id, label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & {label: string; hint?: string}) {
  return <div className="space-y-1.5">
    <Label.Root htmlFor={id} className="block text-sm font-bold">{label}</Label.Root>
    <input id={id} className="field" {...props} />
    {hint && <p className="subtle text-xs">{hint}</p>}
  </div>;
}

export function Badge({ children, tone = "neutral" }: {children: ReactNode; tone?: "neutral" | "critical" | "good"}) {
  const tones = {
    neutral: "bg-[#eceef0] text-[#343941] dark:bg-[#343941] dark:text-[#f1f2f3]",
    critical: "bg-[#fbe4e4] text-[#8d2024] dark:bg-[#51252a] dark:text-[#ffe1e1]",
    good: "bg-[#d8f2ea] text-[#125e4c] dark:bg-[#1c493e] dark:text-[#d9f7ee]",
  };
  return <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-bold", tones[tone])}>{children}</span>;
}

export function Toggle({ checked, onCheckedChange, label, showLabel = true }: {checked: boolean; onCheckedChange: (value: boolean) => void; label: string; showLabel?: boolean}) {
  return <div className="flex items-center justify-between gap-3">
    {showLabel && <span className="text-sm font-medium">{label}</span>}
    <Switch.Root checked={checked} onCheckedChange={onCheckedChange} aria-label={label}
      className="h-11 w-16 rounded-full bg-[#858a91] data-[state=checked]:bg-[#b72429]">
      <Switch.Thumb className="block h-9 w-9 translate-x-1 rounded-full bg-white transition-transform data-[state=checked]:translate-x-6" />
    </Switch.Root>
  </div>;
}

export function Modal({ open, onOpenChange, title, children }: {
  open: boolean; onOpenChange: (value: boolean) => void; title: string; children: ReactNode;
}) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
      <Dialog.Content className="surface fixed top-1/2 left-1/2 z-50 max-h-[92vh] w-[min(94vw,34rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto p-6">
        <Dialog.Title className="text-xl font-bold">{title}</Dialog.Title>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
