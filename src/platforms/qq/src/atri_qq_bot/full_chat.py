"""SnowLuma uses the same complete QQ application as the NapCat transport."""
from http import HTTPStatus
import secrets


def full_chat_config(settings, *, loader=None):
    if loader is None:
        from atri_shared.config import load_config
        loader = load_config
    # Reuse shared personality, account, memory and media settings. Override
    # local listeners and, when explicitly selected, proactive scheduling ownership.
    overrides = {
        'HOST': '127.0.0.1', 'PORT': settings['onebot_port'],
        'WEBUI_ENABLED': 'false', 'CORE_API_ENABLED': 'true',
        'CORE_API_HOST': '127.0.0.1', 'CORE_API_PORT': settings['core_port'],
        'CORE_API_KEY': settings['core_api_key'],
    }
    # One sender owns proactive delivery in this instance. Keep the regular
    # NapCat configuration untouched when AstrBot's plugin owns scheduling.
    if settings.get('proactive_owner') == 'astrbot':
        overrides.update(IDLE_PROACTIVE_ENABLED='false', GROUP_PROACTIVE_ENABLED='false')
    return loader(overrides=overrides)


def authenticated_relay(token):
    if not token:
        raise ValueError('Full QQ relay token is required')

    def check(connection, request):
        supplied = request.headers.get('Authorization', '')
        if request.path != '/onebot' or not secrets.compare_digest(supplied, 'Bearer ' + token):
            return connection.respond(HTTPStatus.UNAUTHORIZED, 'Unauthorized\n')
        return None
    return check


async def serve_full_chat(settings):
    from .onebot.server import run_server
    await run_server(full_chat_config(settings), websocket_options={
        'process_request': authenticated_relay(settings['core_api_key']),
        'max_size': 16 * 1024 * 1024,
    }, proactive_owner=settings.get('proactive_owner', 'core'))
