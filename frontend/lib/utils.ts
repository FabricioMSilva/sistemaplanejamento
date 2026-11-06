type ClassValue = string | false | null | undefined | 0;

/** Junta classes condicionais (equivalente leve a clsx) sem dependência extra. */
export function cn(...classes: ClassValue[]) {
  return classes.filter(Boolean).join(" ");
}
