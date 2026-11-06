"""Native AstrBot command gate; account-bound transport, no chat generation.

The existing QQ socket remains the only outbound transport. Never await a gate
inside its receive loop: native handlers need that loop to resolve QQ actions.
"""
import asyncio
from collections import OrderedDict
from contextlib import suppress
import json
from urllib.parse import urlsplit

from websockets.asyncio.client import connect


class PluginGate:
    def __init__(self, settings, action, *, timeout=3):
        endpoint = urlsplit(settings['url'])
        if (endpoint.scheme != 'ws' or endpoint.hostname != '127.0.0.1'
                or endpoint.path != '/ws' or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment or not settings.get('token')
                or not str(settings.get('account', '')).isdigit()):
            raise ValueError('Plugin gate requires an authenticated local account binding')
        self.settings, self.action, self.timeout = settings, action, timeout
        self.ready = asyncio.Event()
        self.socket = None
        self.runner = None
        self.pending = {}
        self.seen = OrderedDict()

    def start(self):
        if self.runner is None:
            self.runner = asyncio.create_task(self._run())

    async def close(self):
        if self.runner:
            self.runner.cancel()
            with suppress(asyncio.CancelledError):
                await self.runner
            self.runner = None

    async def dispatch(self, event):
        if str(event.get('self_id', '')) != str(self.settings['account']):
            return False
        key = str(event.get('message_id', ''))
        if not key or event.get('post_type') != 'message':
            return False
        if key in self.seen:
            return True
        # Offline before submission: keep the original chatbot available.
        if not self.ready.is_set():
            return False
        if len(self.pending) >= 128:
            return True
        self.seen[key] = None
        if len(self.seen) > 2048:
            self.seen.popitem(last=False)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.socket.send(json.dumps(event, ensure_ascii=False))
            return await asyncio.wait_for(future, self.timeout)
        except (Exception, asyncio.TimeoutError):
            # A submitted command might already have executed. Do not replay it
            # or give the same event to another responder after an unknown result.
            return True
        finally:
            self.pending.pop(key, None)

    async def observe(self, event):
        if str(event.get('self_id')) == str(self.settings['account']) and self.ready.is_set():
            with suppress(Exception):
                await self.socket.send(json.dumps(event, ensure_ascii=False))

    async def _execute(self, socket, request):
        response = {'echo': request.get('echo')}
        try:
            params = request.get('params', {})
            if request['action'] == 'atri_plugin_route':
                future = self.pending.get(str(params.get('message_id', '')))
                if future and not future.done():
                    future.set_result(params.get('consumed') is True)
                data = None
            else:
                data = await asyncio.wait_for(self.action(request['action'], params), 180)
            response.update(status='ok', retcode=0, data=data)
        except Exception:
            response.update(status='failed', retcode=-1, data=None, wording='Platform action failed')
        with suppress(Exception):
            await socket.send(json.dumps(response, ensure_ascii=False))

    async def _run(self):
        while True:
            tasks = set()
            try:
                async with connect(self.settings['url'], additional_headers={
                        'Authorization': 'Bearer ' + self.settings['token'],
                        'X-Self-ID': str(self.settings['account']),
                        'X-Client-Role': 'Universal'}, open_timeout=2,
                        max_size=16 * 1024 * 1024) as socket:
                    self.socket = socket
                    self.ready.set()
                    async for raw in socket:
                        request = json.loads(raw)
                        if not isinstance(request, dict) or not isinstance(request.get('action'), str):
                            continue
                        if len(tasks) >= 64:
                            await socket.send(json.dumps({'echo': request.get('echo'),
                                'status': 'failed', 'retcode': -1, 'wording': 'Plugin gate busy'}))
                            continue
                        task = asyncio.create_task(self._execute(socket, request))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
            except Exception:
                pass
            finally:
                self.ready.clear()
                self.socket = None
                for future in self.pending.values():
                    if not future.done():
                        future.set_result(True)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(2)


def load_settings(name):
    from atrium_runtime import user_root
    path = user_root() / 'data/plugins/astrbot/shared/ingress.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get(name) if data.get('enabled') is True else None
    except (OSError, ValueError):
        return None
