const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://node.ciris.ai";

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit & { token?: string }
): Promise<T> {
  const url = `${API_URL}${path}`;
  const { token, ...fetchOptions } = options || {};
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(url, {
    ...fetchOptions,
    headers,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}
