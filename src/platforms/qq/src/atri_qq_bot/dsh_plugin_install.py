"""Small, version-checked DSH integration; no SDK or upstream logic fork."""
import hashlib
import json
from pathlib import Path
import time

ANCHOR = "  bot.onPrivateMessage(async (event) => {"
START = "  // ATRI shared plugin ingress BEGIN"
END = "  // ATRI shared plugin ingress END"
CULTURE_ANCHOR = "    let content = [{ type: 'text', text: withSlangContext(promptText) }];"
CULTURE_HOOK = "    promptText = await atriPluginGate?.culturePrompt(key, promptText) ?? promptText;"


def install(root):
    root = Path(root)
    path = root.parent / 'QQ_Backends/DSH-QQ/src/bridge.js'
    before = path.read_bytes()
    text = before.decode('utf-8')
    module = (Path(__file__).parent / 'plugin_gate.mjs').resolve().as_uri()
    manifest = str(root / 'data/plugins/astrbot/shared/ingress.json')
    block = (START + '\n' + f'  const atriPluginGate = (await import({json.dumps(module)}))'
             + f'.attachDSHGate(bot, import.meta.url, {json.dumps(manifest)});\n' + END + '\n\n')
    if START in text:
        if text.count(START) != 1 or text.count(END) != 1:
            raise ValueError('DSH ingress markers changed; no files modified')
        first, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        after = first + block.rstrip('\n') + tail
    else:
        if text.count(ANCHOR) != 1 or 'SnowLumaWebSocketClient' not in text:
            raise ValueError('DSH upstream entry changed; review integration before updating')
        after = text.replace(ANCHOR, block + ANCHOR, 1)
    # Both normal and queued/wake delivery must read the same account-bound
    # culture context. Refuse an upstream change rather than half-installing.
    after = after.replace(CULTURE_HOOK + '\n', '')
    if after.count(CULTURE_ANCHOR) != 2:
        raise ValueError('DSH prompt entry changed; no files modified')
    after = after.replace(CULTURE_ANCHOR, CULTURE_HOOK + '\n' + CULTURE_ANCHOR)
    result = after.encode('utf-8')
    if result != before:
        digest = hashlib.sha256(before).hexdigest()
        backup = root / 'dev/workspace/backups/shared-plugins' / digest
        backup.mkdir(parents=True, exist_ok=True)
        (backup / 'bridge.js').write_bytes(before)
        temporary = path.with_suffix('.atri-tmp')
        temporary.write_bytes(result)
        temporary.replace(path)
    return hashlib.sha256(result).hexdigest()
