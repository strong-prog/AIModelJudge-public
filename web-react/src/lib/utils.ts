/** Merge class names, filtering falsy values */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/** Format bytes to human-readable string */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + units[i];
}

/** Format a date to relative time string */
export function timeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}

/** Truncate string in the middle */
export function truncateMiddle(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s;
  const half = Math.floor((maxLen - 3) / 2);
  return s.slice(0, half) + "..." + s.slice(s.length - half);
}

/** Debounce a function */
export function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  ms: number
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout>;
  return (...args: Parameters<T>) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/** Check if a cron expression matches given timestamp */
export function cronMatch(_expr: string, _date?: Date): boolean {
  // Simplified — full implementation depends on cron-parser
  return false;
}

/** CSS variable shorthand */
export const cssVar = (name: string, fallback = ""): string =>
  `var(--${name}${fallback ? `, ${fallback}` : ""})`;
