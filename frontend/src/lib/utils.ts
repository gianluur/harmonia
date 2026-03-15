import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes safely. Used everywhere in components. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
