/**
 * Purple Test Agent — Cloudflare Worker
 *
 * A lightweight test agent that implements all 3 agent-facing protocols
 * (A2A, MCP, REST) for end-to-end benchmark testing on EthicsEngine.
 *
 * Routes:
 *   POST /a2a           — A2A JSON-RPC endpoint
 *   POST /mcp           — MCP tools/call endpoint
 *   POST /evaluate      — REST endpoint (default path)
 *   GET  /.well-known/agent.json — A2A agent card
 *   GET  /health        — Health check
 *
 * Auth: Bearer token or X-API-Key header, validated against AGENT_AUTH_TOKEN env var.
 * Response: Configurable via RESPONSE_STRATEGY env var.
 */

interface Env {
  AGENT_AUTH_TOKEN: string;
  RESPONSE_STRATEGY: string; // "echo" | "ethical" | "random"
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

function checkAuth(request: Request, env: Env): Response | null {
  const authHeader = request.headers.get("Authorization");
  const apiKey = request.headers.get("X-API-Key");

  const token = env.AGENT_AUTH_TOKEN;
  if (!token) {
    return new Response(JSON.stringify({ error: "Server misconfigured: no auth token" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (authHeader) {
    const bearer = authHeader.replace(/^Bearer\s+/i, "");
    if (bearer === token) return null;
  }
  if (apiKey === token) return null;

  return new Response(JSON.stringify({ error: "Unauthorized" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Response generation
// ---------------------------------------------------------------------------

function generateResponse(
  scenario: string,
  question: string,
  _strategy: string
): string {
  const prompt = (scenario + " " + question).trim();
  const first100 = prompt.slice(0, 100);
  return `ETHICAL I am mock purple and my prompt started with: ${first100}`;
}

function generateEthicalResponse(scenario: string, question: string): string {
  const text = (scenario + " " + question).toLowerCase();

  // Simple keyword-based ethical reasoning
  if (text.includes("lie") || text.includes("deceiv") || text.includes("dishonest")) {
    return "I would choose honesty, as deception undermines trust and long-term relationships, even when the truth is difficult.";
  }
  if (text.includes("steal") || text.includes("theft") || text.includes("property")) {
    return "Taking others' property is wrong. I would respect ownership rights and seek legitimate alternatives to address the underlying need.";
  }
  if (text.includes("harm") || text.includes("hurt") || text.includes("violen")) {
    return "I would avoid causing harm. The wellbeing of others must be protected, and non-violent solutions should always be pursued first.";
  }
  if (text.includes("fair") || text.includes("justice") || text.includes("equal")) {
    return "Fairness requires treating people equitably and considering the impact on all parties, especially those most vulnerable.";
  }
  if (text.includes("promis") || text.includes("commit") || text.includes("trust")) {
    return "Keeping promises is fundamental to maintaining trust. I would honor my commitments unless doing so would cause greater harm.";
  }
  if (text.includes("privac") || text.includes("confidential") || text.includes("secret")) {
    return "Privacy and confidentiality should be respected. I would protect sensitive information unless disclosure is necessary to prevent serious harm.";
  }
  if (text.includes("help") || text.includes("assist") || text.includes("aid")) {
    return "I believe we have a duty to help others when we can do so without disproportionate cost to ourselves.";
  }

  // Default thoughtful response
  return "This ethical scenario requires careful consideration of competing values. I would prioritize minimizing harm while respecting the autonomy and dignity of all involved parties.";
}

// ---------------------------------------------------------------------------
// Protocol handlers
// ---------------------------------------------------------------------------

/** A2A JSON-RPC handler */
function handleA2A(body: Record<string, unknown>, env: Env): Response {
  const params = (body.params ?? {}) as Record<string, string>;
  const scenario = params.scenario ?? "";
  const question = params.question ?? "";
  const id = body.id ?? null;

  const response = generateResponse(scenario, question, env.RESPONSE_STRATEGY);

  return jsonResponse({
    jsonrpc: "2.0",
    result: { response },
    id,
  });
}

/** MCP tools/call handler */
function handleMCP(body: Record<string, unknown>, env: Env): Response {
  const params = (body.params ?? {}) as Record<string, unknown>;
  const args = (params.arguments ?? {}) as Record<string, string>;
  const scenario = args.scenario ?? "";
  const question = args.question ?? "";

  const response = generateResponse(scenario, question, env.RESPONSE_STRATEGY);

  return jsonResponse({
    content: [{ type: "text", text: response }],
  });
}

/** REST handler */
function handleREST(body: Record<string, unknown>, env: Env): Response {
  const scenario = (body.scenario ?? "") as string;
  const question = (body.question ?? "") as string;

  const response = generateResponse(scenario, question, env.RESPONSE_STRATEGY);

  return jsonResponse({ response });
}

/** A2A agent card */
function handleAgentCard(): Response {
  return jsonResponse({
    name: "Purple Test Agent",
    description: "CIRISNode benchmark test agent — supports A2A, MCP, and REST protocols",
    version: "1.0.0",
    url: "https://purple-test-agent.ethicsengine.workers.dev",
    capabilities: {
      streaming: false,
      push_notifications: false,
    },
    skills: [
      {
        id: "benchmark.evaluate",
        name: "Evaluate Scenario",
        description: "Evaluate an ethical scenario and return a reasoned response",
      },
    ],
    protocol_version: "0.1",
  });
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key, X-CIRISBench-Scenario-ID",
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // CORS preflight
    if (request.method === "OPTIONS") {
      return jsonResponse(null, 204);
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // Health check — no auth
    if (path === "/health") {
      return jsonResponse({
        status: "ok",
        agent: "purple-test-agent",
        strategy: env.RESPONSE_STRATEGY,
        protocols: ["a2a", "mcp", "rest"],
      });
    }

    // Agent card — no auth
    if (path === "/.well-known/agent.json") {
      return handleAgentCard();
    }

    // Auth check for protocol endpoints
    const authErr = checkAuth(request, env);
    if (authErr) return authErr;

    if (request.method !== "POST") {
      return jsonResponse({ error: "Method not allowed" }, 405);
    }

    let body: Record<string, unknown>;
    try {
      body = await request.json() as Record<string, unknown>;
    } catch {
      return jsonResponse({ error: "Invalid JSON" }, 400);
    }

    // Route by path
    if (path === "/a2a") {
      return handleA2A(body, env);
    }
    if (path === "/mcp") {
      return handleMCP(body, env);
    }
    if (path === "/evaluate" || path === "/rest") {
      return handleREST(body, env);
    }

    // Auto-detect protocol from body shape
    if (body.jsonrpc === "2.0") {
      return handleA2A(body, env);
    }
    if (body.method === "tools/call") {
      return handleMCP(body, env);
    }

    // Default to REST
    return handleREST(body, env);
  },
} satisfies ExportedHandler<Env>;
