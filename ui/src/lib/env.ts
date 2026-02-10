/**
 * Environment variable access for Cloudflare Workers.
 *
 * Cloudflare Workers pass env bindings via the fetch handler, not process.env.
 * Secrets set via `wrangler secret put` may not always appear in process.env.
 *
 * This helper tries getCloudflareContext().env first (direct Worker bindings),
 * then falls back to process.env.
 */

type CloudflareEnv = Record<string, string | undefined>;

function getWorkerEnv(): CloudflareEnv | null {
  try {
    // Dynamic import to avoid build errors when not on CF Workers
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { getCloudflareContext } = require("@opennextjs/cloudflare");
    const ctx = getCloudflareContext();
    return (ctx?.env as CloudflareEnv) ?? null;
  } catch {
    return null;
  }
}

export function getEnv(key: string): string | undefined {
  const workerEnv = getWorkerEnv();
  if (workerEnv?.[key]) return workerEnv[key];
  return process.env[key];
}
