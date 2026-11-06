"""Read the combined SnowLuma/DSH logs without probing or starting services."""
from pathlib import Path

from .log_reader import ANSI_RE, _RECORD_TIME, chronological
from .snowluma_launcher import SnowLumaLauncher


def _label(text: str, label: str) -> str:
    """Keep timestamps at the start so chronological() can still merge them."""
    lines = []
    for line in ANSI_RE.sub('', text).splitlines():
        match = _RECORD_TIME.match(line)
        if match:
            end = match.end()
            if line[end:end + 1] == ']':
                end += 1
            lines.append(f'{line[:end]} [{label}] {line[end:].lstrip()}')
        else:
            # Preserve indentation and traceback association with the record.
            lines.append(line if lines else f'[{label}] {line}')
    return '\n'.join(lines)


def combined_tail(backend: Path) -> str:
    from . import log_reader

    def read(path):
        try:
            if not path.is_file():
                return ''
            limit = 12000
            size = path.stat().st_size
            text = log_reader._tail_bytes(path, limit)
            if size > limit and '\n' in text:
                text = text.split('\n', 1)[1]
            return text
        except OSError:
            return f'{path.name} 暂时无法读取，请稍后刷新。'

    _, startup = SnowLumaLauncher()._paths()
    state = backend / 'state'
    # bridge.log keeps updating even if the original stdout consumer disappears.
    # It mirrors stdout: select one, otherwise every bridge event appears twice.
    bridge = read(state / 'bridge.log')
    fallback = not bridge.strip() or bridge == 'bridge.log 暂时无法读取，请稍后刷新。'
    streams = [bridge] if bridge else []
    if fallback:
        streams.append(read(state / 'bridge.stdout.log'))
    streams.append(read(state / 'bridge.stderr.log'))
    for path, label in (
        (startup, 'SnowLuma 启动'),
        (state / 'qq-connect.log', 'QQ 连接'),
        (state / 'lifecycle.log', 'DSH 启停'),
        (state / 'dsh.stdout.log', 'DSH 核心'),
        (state / 'dsh.stderr.log', 'DSH 核心'),
        (state / 'qq-activity.log', '聊天'),
    ):
        streams.append(_label(read(path), label))
    return chronological(*streams, newest_first=True)
