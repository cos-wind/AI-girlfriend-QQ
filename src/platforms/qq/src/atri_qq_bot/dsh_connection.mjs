// Startup adaptation only; reuse upstream configuration reader and SDK retry loop.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function boundConnection(cfg, root) {
  const binding = JSON.parse(fs.readFileSync(path.join(root, 'desktop-launch.json'), 'utf8').replace(/^\uFEFF/, ''));
  const account = String(binding.account ?? '');
  if (!/^\d{5,12}$/.test(account)) throw new Error('Missing DSH account binding');
  const { readOneBotTokens, snowLumaHomeCandidates } = await import(pathToFileURL(path.join(root, 'src/snowluma-conn.js')).href);
  const sl = cfg.snowluma;
  for (const home of snowLumaHomeCandidates({ cfg })) {
    const entry = readOneBotTokens(home).find(value => value.uin === account);
    // Never bootstrap from another account or silently change either endpoint.
    if (!entry?.http || !entry?.ws) continue;
    if (new URL(`http://${entry.http.host}:${entry.http.port}`).href !== new URL(sl.httpUrl).href
        || new URL(`ws://${entry.ws.host}:${entry.ws.port}`).href !== new URL(sl.wsUrl).href) continue;
    return { account, entry };
  }
  return { account, entry: null };
}

export async function connectionOptions(cfg, root) {
  let token = cfg.snowluma.accessToken;
  try {
    const { entry } = await boundConnection(cfg, root);
    // HTTP and WS tokens are independent. No network probe needed to read them.
    if (entry && entry.http.token === token) token = entry.ws.token;
  } catch { /* Unavailable local config: retain the upstream repair path. */ }
  return { url: cfg.snowluma.wsUrl, accessToken: token || undefined,
    reconnect: { minDelayMs: 1000, maxDelayMs: 2000 } };
}

export async function discoverBoundConnection(cfg, root, discover) {
  const { account, entry } = await boundConnection(cfg, root);
  const result = await discover({ cfg, baseUrl: cfg.snowluma.httpUrl,
    token: entry?.http.token || cfg.snowluma.accessToken, homeDirs: [], timeoutMs: 1500 });
  if (!result.ok) return result;
  if (String(result.self?.user_id ?? '') !== account) {
    return { ok: false, error: 'SnowLuma account differs from DSH binding; connection unchanged' };
  }
  return { ...result, wsToken: entry?.ws.token ?? result.wsToken,
    wsUrl: cfg.snowluma.wsUrl, baseUrl: cfg.snowluma.httpUrl };
}
