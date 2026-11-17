/**
 * A minimal MCP client (streamable HTTP, protocol 2025-03-26) for the chat: it calls one tool on one of our MCP servers and
 * returns the tool's JSON result. One session per call (initialize, notifications/initialized, tools/call): the calls are
 * rare and a session costs one extra round trip, so nothing is kept between them.
 */
import { log } from '../logger.js';

const PROTOCOL = '2025-03-26';
const TIMEOUT_MS = 45_000;

interface RpcMessage {
  id?: number;
  result?: { content?: Array<{ type: string; text?: string }>; isError?: boolean; structuredContent?: unknown };
  error?: { message?: string };
}

async function post(url: string, body: unknown, session: string | null): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' };
  if (session) headers['Mcp-Session-Id'] = session;
  return fetch(url, { method: 'POST', headers, body: JSON.stringify(body), signal: AbortSignal.timeout(TIMEOUT_MS) });
}

/** The reply is JSON or a one-message SSE stream; both carry the JSON-RPC message we want. */
async function readRpc(res: Response, id: number): Promise<RpcMessage> {
  const text = await res.text();
  if (!res.ok) throw new Error(`MCP server answered HTTP ${res.status}`);
  const type = res.headers.get('content-type') ?? '';
  const messages: RpcMessage[] = type.includes('text/event-stream')
    ? text.split('\n').filter((l) => l.startsWith('data:')).map((l) => JSON.parse(l.slice(5).trim()) as RpcMessage)
    : [JSON.parse(text) as RpcMessage];
  const reply = messages.find((m) => m.id === id);
  if (!reply) throw new Error('MCP server sent no reply');
  if (reply.error) throw new Error(reply.error.message ?? 'MCP error');
  return reply;
}

/** Calls one tool and returns its structured result. A tool that raised reports its message, never a guess. */
export async function callMcpTool<T = unknown>(url: string, tool: string, args: Record<string, unknown>): Promise<T> {
  const init = await post(url, { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: 'cam-daemon', version: '1' } } }, null);
  const session = init.headers.get('mcp-session-id');
  await readRpc(init, 1);
  await post(url, { jsonrpc: '2.0', method: 'notifications/initialized' }, session);
  const reply = await readRpc(await post(url, { jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: tool, arguments: args } }, session), 2);
  const result = reply.result;
  if (!result) throw new Error('MCP server sent no result');
  const text = result.content?.find((c) => c.type === 'text')?.text ?? '';
  if (result.isError) {
    log.warn(`[RfqChat] MCP tool ${tool} refused: ${text}`);
    throw new Error(text || `${tool} failed`);
  }
  return (result.structuredContent ?? (text ? JSON.parse(text) : null)) as T;
}
