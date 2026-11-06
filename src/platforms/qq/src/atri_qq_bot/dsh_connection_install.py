"""Maintain narrow startup hooks without forking the SDK or upstream discovery."""
import hashlib
import json
from pathlib import Path

INIT = '''  const bot = new SnowLumaWebSocketClient({
    url: cfg.snowluma.wsUrl,
    accessToken: cfg.snowluma.accessToken || undefined,
    reconnect: true
  });'''
HEAL = '''  let tokenHealAt = 0;
  async function healTokenIfStale(reason) {
    const now = Date.now();
    if (now - tokenHealAt < 10000) return;   // 节流：close 事件会连续触发
    tokenHealAt = now;
    try {
      const r = await discoverSnowLumaConnection({ cfg, timeoutMs: 4000 });
      if (!r.ok) {
        log(`⚠️ token 自愈失败（${reason}）：${r.error}`);
        return;
      }
      await applyHealedTokens(r);
      log(`   自愈完成：账号 ${r.self?.user_id ?? '?'}（${reason}）`);
    } catch (error) {
      log(`⚠️ token 自愈异常：${error?.message ?? error}`);
    }
  }'''
START = '  // ATRI fast connection {name} BEGIN'
END = '  // ATRI fast connection {name} END'


def _replace(text, name, original, replacement):
    start, end = START.format(name=name), END.format(name=name)
    if start in text or end in text:
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError('DSH connection markers changed; no files modified')
        first, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        newline = '\r\n' if rest.startswith('\r\n') else '\n'
        block = (start + '\n' + replacement + '\n' + end).replace('\n', newline)
        return first + block + tail
    matches = [(value, newline) for value, newline in [(original, '\n'), (original.replace('\n', '\r\n'), '\r\n')]
               if value in text]
    if len(matches) != 1 or text.count(matches[0][0]) != 1:
        raise ValueError('DSH connection upstream anchor changed; no files modified')
    value, newline = matches[0]
    block = (start + '\n' + replacement + '\n' + end).replace('\n', newline)
    return text.replace(value, block, 1)


def install(root):
    root = Path(root)
    path = root.parent / 'QQ_Backends/DSH-QQ/src/bridge.js'
    before = path.read_bytes()
    text = before.decode('utf-8')
    module = json.dumps((Path(__file__).parent / 'dsh_connection.mjs').resolve().as_uri())
    init = ('  const bot = new SnowLumaWebSocketClient({\n'
            f'    ...await (await import({module})).connectionOptions(cfg, ROOT)\n  }});')
    heal = HEAL.replace('let tokenHealAt = 0;', 'let tokenHealAt = -Infinity;\n  let tokenHealPending = false;')
    heal = heal.replace('if (now - tokenHealAt < 10000) return;   // 节流：close 事件会连续触发',
                        'if (tokenHealPending || now - tokenHealAt < 1000) return;')
    heal = heal.replace('    tokenHealAt = now;', '    tokenHealAt = now;\n    tokenHealPending = true;')
    heal = heal.replace('discoverSnowLumaConnection({ cfg, timeoutMs: 4000 })',
                        f'(await import({module})).discoverBoundConnection(cfg, ROOT, discoverSnowLumaConnection)')
    heal = heal.replace('    }\n  }', '    } finally {\n      tokenHealPending = false;\n    }\n  }')
    text = _replace(text, 'init', INIT, init)
    text = _replace(text, 'heal', HEAL, heal)
    result = text.encode('utf-8')
    if result == before:
        return False
    backup = root / 'dev/workspace/backups/dsh-connection' / hashlib.sha256(before).hexdigest()
    backup.mkdir(parents=True, exist_ok=True)
    (backup / 'bridge.js').write_bytes(before)
    temporary = path.with_suffix('.connection-tmp')
    try:
        temporary.write_bytes(result)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True
