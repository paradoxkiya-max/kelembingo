// Style reminder: formatting stays compact and high-contrast so values fit the original mobile metric pills.

export function etb(value: unknown) { return `${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} ETB`; }
export function walletValue(value: unknown) { return typeof value === "object" && value !== null && "value" in value ? Number((value as { value?: number }).value || 0) : Number(value || 0); }
export function relativeDate(value: unknown) { if (!value) return "—"; const date = new Date(value as string | number); if (Number.isNaN(date.getTime())) return "—"; const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000)); if (minutes < 1) return "just now"; if (minutes < 60) return `${minutes}m ago`; if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`; return `${Math.floor(minutes / 1440)}d ago`; }
