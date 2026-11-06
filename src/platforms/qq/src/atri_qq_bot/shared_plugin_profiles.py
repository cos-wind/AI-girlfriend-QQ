"""Native AstrBot profile registration, run only by its isolated interpreter.

No dashboard authentication or credential changes. Register before the host
opens its database; keep user-edited profiles and unrelated routes intact.
"""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys


async def register(data):
    from astrbot.core.db.sqlite import SQLiteDatabase
    from astrbot.core.utils.shared_preferences import SharedPreferences

    data = Path(data)
    config = json.loads((data / 'cmd_config.json').read_text(encoding='utf-8-sig'))
    db = SQLiteDatabase(str(data / 'data_v4.db'))
    await db.initialize()
    sp = SharedPreferences(db)
    try:
        mapping = await sp.global_get('abconf_mapping', {})
        mapping['atri-ingress'] = {'path': 'abconf_atri-ingress.json', 'name': 'QQ 插件入口'}
        await sp.global_put('abconf_mapping', mapping)
        previous = await sp.global_get('umop_config_routing', {})
        routes = {p['id'] + '::': 'atri-ingress' for p in config.get('platform', [])
                  if p.get('id') in ('atri-plugin-napcat', 'atri-plugin-dsh')}
        # Optional account profile keeps passive plugins off the other QQ.
        # No copy is generated here: preserve the user's scoped settings.
        if (data / 'config/abconf_atri-dsh.json').is_file():
            mapping['atri-dsh'] = {'path': 'abconf_atri-dsh.json', 'name': 'SnowLuma 插件入口'}
            await sp.global_put('abconf_mapping', mapping)
            if 'atri-plugin-dsh::' in routes:
                routes['atri-plugin-dsh::'] = 'atri-dsh'
        routes.update({k: v for k, v in previous.items() if k not in routes})
        await sp.global_put('umop_config_routing', routes)
    finally:
        sp._scheduler.shutdown(wait=False)
        sp._sync_loop.call_soon_threadsafe(sp._sync_loop.stop)
        await db.engine.dispose()


if __name__ == '__main__':
    source = Path(sys.argv[1])
    sys.path.insert(0, str(source))
    asyncio.run(register(Path(os.environ['ASTRBOT_ROOT']) / 'data'))
    sys.argv = [str(source / 'main.py'), '--webui-dir', str(source / 'data/dist')]
    runpy.run_path(str(source / 'main.py'), run_name='__main__')
