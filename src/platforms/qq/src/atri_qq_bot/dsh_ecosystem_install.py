"""Install small, anchor-checked hooks; preserve upstream source and configuration."""
import hashlib
import json
from pathlib import Path

IMPORT_START = '// ATRI QQ ecosystem import BEGIN'
IMPORT_END = '// ATRI QQ ecosystem import END'
INIT_START = '    // ATRI QQ ecosystem init BEGIN'
INIT_END = '    // ATRI QQ ecosystem init END'
ROUTE_START = '        // ATRI QQ ecosystem route BEGIN'
ROUTE_END = '        // ATRI QQ ecosystem route END'
MCP_START = '// ATRI QQ ecosystem tools BEGIN'
MCP_END = '// ATRI QQ ecosystem tools END'
PROMPT_START = '            // ATRI QQ interaction prompt BEGIN'
PROMPT_END = '            // ATRI QQ interaction prompt END'
INIT_ANCHOR = '    const v2SessionAllowed = isSessionAllowedInCurrentMode;'
ROUTE_ANCHOR = "        if (req.method === 'GET' && url.pathname === '/api/status') {"
MCP_ANCHOR = 'await server.connect(new StdioServerTransport());'
PROMPT_ANCHOR = "            sendPoke: 'qq_send_poke',"


def replace_block(source, start, end, block, anchor=None, prepend=False):
    if start in source or end in source:
        if source.count(start) != 1 or source.count(end) != 1:
            raise ValueError('DSH ecosystem markers changed; no files modified')
        first, rest = source.split(start, 1)
        _, tail = rest.split(end, 1)
        return first + block + tail
    if prepend:
        return block + '\n' + source
    if source.count(anchor) != 1:
        raise ValueError('DSH ecosystem upstream anchor changed; no files modified')
    return source.replace(anchor, block + '\n' + anchor, 1)


def install(root):
    root = Path(root)
    backend = root.parent / 'QQ_Backends/DSH-QQ'
    paths = [backend / 'src/bridge.js', backend / 'src/mcp-snowluma-safe.js']
    before = [p.read_bytes() for p in paths]
    bridge, mcp = [b.decode('utf-8') for b in before]
    if 'SnowLumaWebSocketClient' not in bridge or 'async function agentApi(' not in mcp:
        raise ValueError('Unsupported DSH ecosystem source; no files modified')
    module = json.dumps((Path(__file__).parent / 'qq_ecosystem.mjs').resolve().as_uri())
    interactions = json.dumps((Path(__file__).parent / 'qq_interactions.mjs').resolve().as_uri())
    media = json.dumps((Path(__file__).parent / 'qq_media.mjs').resolve().as_uri())
    bridge = replace_block(bridge, IMPORT_START, IMPORT_END,
        f'{IMPORT_START}\nimport {{ createEcosystem }} from {module};\nimport {{ createInteractions }} from {interactions};\nimport {{ authorizeMedia }} from {media};\n{IMPORT_END}', prepend=True)
    init = '''    // ATRI QQ ecosystem init BEGIN
    const atriQQDeps = {
      getConfig: () => cfg, getMode: () => currentMode,
      authorize: (key, token) => agentTokenOk(key, token) && isSessionAllowedInCurrentMode(key),
      getExpectedAccount: () => JSON.parse(fs.readFileSync(path.join(ROOT, 'desktop-launch.json'), 'utf8')).account,
      ledgerPath: path.join(STATE_DIR, 'atri-ecosystem-sends.json'),
      audit: (value) => {
        if (SENSITIVE_RE.test(value) || [...KNOWN_AGENT_TOKENS].some(t => t && value.includes(t))) {
          throw Object.assign(new Error('内容包含路径、凭据或会话令牌，已阻止发送'), { status: 403 });
        }
      },
      send: (kind, id, value) => onebotSend(kind, id, value),
      action: async (name, params) => {
        const url = new URL(cfg.snowluma.httpUrl);
        if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
            || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
          throw new Error('SnowLuma must use a bound loopback HTTP endpoint');
        }
        url.pathname = '/' + name;
        const response = await fetch(url, { method: 'POST', redirect: 'error',
          headers: { 'content-type': 'application/json', ...(cfg.snowluma.accessToken ? { Authorization: `Bearer ${cfg.snowluma.accessToken}` } : {}) },
          body: JSON.stringify(params), signal: AbortSignal.timeout(15000) });
        const result = await response.json();
        if (!response.ok || result?.status !== 'ok' || result.retcode !== 0) throw new Error('SnowLuma action failed');
        return result.data;
      },
    };
    const atriEcosystem = createEcosystem(atriQQDeps);
    const atriInteractions = createInteractions({
      ...atriQQDeps, ledgerPath: path.join(STATE_DIR, 'atri-interaction-sends.json'),
      captureGuard: (key) => {
        const guard = captureSendGuard(key);
        const check = () => {
          try { guard(); } catch { throw Object.assign(new Error('会话、模式或白名单已变化'), { status: 403 }); }
          if (socialV2.paused || shouldBlockSilentReply(key)) {
            throw Object.assign(new Error('二代聊天已暂停或当前聊天处于静默状态'), { status: 403 });
          }
        };
        check();
        return check;
      },
      reserve: (key) => {
        const st = getSocialV2State(key);
        const times = st.sendTimes || [];
        const send = cfg.socialV2?.send ?? {};
        const now = Date.now();
        if ((Number(send.maxSendPerMinute) > 0 && times.filter(t => now - t < 60000).length >= Number(send.maxSendPerMinute))
            || (Number(send.maxSendPerHour) > 0 && times.filter(t => now - t < 3600000).length >= Number(send.maxSendPerHour))) {
          throw Object.assign(new Error('发送频率超限，请稍后再试'), { status: 429 });
        }
        st.sendTimes = [...times, now].slice(-500);
        saveSocialV2State();
      },
      record: (key, label) => {
        const st = getSocialV2State(key);
        st.lastActionAt = st.lastAiReplyAt = Date.now();
        st.wakeConfig.noActionCount = 0;
        recordSentMessagesV2(key, [label]);
      },
    });
    // ATRI QQ ecosystem init END'''
    bridge = replace_block(bridge, INIT_START, INIT_END, init, INIT_ANCHOR)
    route = '''        // ATRI QQ ecosystem route BEGIN
        if (req.method === 'POST' && url.pathname === '/api/socialV2/atri-media-authorize') {
          const result = authorizeMedia(atriQQDeps, await readBody(), req.headers['x-agent-token']);
          sendJson(result.body, result.status);
          return;
        }
        if (req.method === 'POST' && url.pathname === '/api/socialV2/atri-ecosystem') {
          const body = await readBody();
          const result = await atriEcosystem(body, req.headers['x-agent-token']);
          sendJson(result.body, result.status);
          return;
        }
        if (req.method === 'POST' && url.pathname === '/api/socialV2/atri-interactions') {
          const body = await readBody();
          const result = await atriInteractions(body, req.headers['x-agent-token']);
          sendJson(result.body, result.status);
          return;
        }
        // ATRI QQ ecosystem route END'''
    bridge = replace_block(bridge, ROUTE_START, ROUTE_END, route, ROUTE_ANCHOR)
    prompt = '''            // ATRI QQ interaction prompt BEGIN
            findFaces: 'qq_find_faces',
            sendFace: 'qq_send_face',
            setMessageReaction: 'qq_set_message_reaction',
            atriMedia: 'qq_analyze_video',
            // ATRI QQ interaction prompt END'''
    bridge = replace_block(bridge, PROMPT_START, PROMPT_END, prompt, PROMPT_ANCHOR)
    mcp = replace_block(mcp, MCP_START, MCP_END,
        f'{MCP_START}\n(await import({module})).registerEcosystemTools(server, z, agentApi, serializeModelData, cfg.socialV2?.tools?.atriEcosystem !== false);\n(await import({interactions})).registerInteractionTools(server, z, agentApi, serializeModelData, cfg.socialV2?.tools);\n(await import({media})).registerMediaTools(server, z, agentApi, serializeModelData, cfg.socialV2?.tools);\n{MCP_END}', MCP_ANCHOR)
    after = [bridge.encode('utf-8'), mcp.encode('utf-8')]
    changed = [(p, old, new) for p, old, new in zip(paths, before, after) if old != new]
    # Validate both sources before the first mutation; backup originals by content hash.
    for p, old, _ in changed:
        backup = root / 'dev/workspace/backups/qq-ecosystem' / hashlib.sha256(old).hexdigest()
        backup.mkdir(parents=True, exist_ok=True)
        (backup / p.name).write_bytes(old)
    done = []
    try:
        for p, old, new in changed:
            if p.read_bytes() != old:
                raise RuntimeError('DSH source changed during install; refused overwrite')
            tmp = p.with_suffix('.ecosystem-tmp')
            tmp.write_bytes(new)
            tmp.replace(p)
            done.append((p, old))
    except Exception:
        for p, old in reversed(done):
            tmp = p.with_suffix('.ecosystem-rollback')
            tmp.write_bytes(old)
            tmp.replace(p)
        raise
    return {'changed': [p.name for p, _, _ in changed],
            'sha256': {p.name: hashlib.sha256(new).hexdigest() for p, new in zip(paths, after)}}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    print(json.dumps(install(parser.parse_args().root)))
