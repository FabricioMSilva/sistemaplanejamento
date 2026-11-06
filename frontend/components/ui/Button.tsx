import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const VARIANTS = {
  primary: "border-primary bg-primary text-primary-foreground hover:brightness-110",
  accent: "border-accent bg-accent text-accent-foreground hover:brightness-95",
  secondary: "border-border bg-surface text-foreground hover:border-primary/40 hover:bg-secondary",
  ghost: "border-transparent bg-transparent text-current hover:bg-foreground/10",
  danger: "border-danger bg-danger text-primary-foreground hover:brightness-110",
} as const;

const SIZES = {
  sm: "min-h-8 px-2.5 py-1 text-xs",
  md: "min-h-9 px-3 py-2 text-sm",
  icon: "h-9 w-9 p-0",
} as const;

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, type = "button", ...props }, ref,
) {
  return (
    <button ref={ref} type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg border font-medium transition duration-150",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant], SIZES[size], className,
      )}
      {...props} />
  );
});
