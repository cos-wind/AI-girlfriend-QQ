"""Explicit NapCat lifecycle; never starts the ATRI reply core."""
from threading import Lock

from .napcat_session import launcher


class NapCatLauncher:
    def __init__(self, *, loader=None):
        self._loader = loader or launcher
        self._lock = Lock()

    def _module(self):
        module = self._loader()
        # Discovery may fall back to ordinary QQ. Refuse that fallback before
        # startup OR shutdown; retain the launcher's existing isolation rules.
        executable, _ = module.validate_qq_isolation(module.qq_executable(), module.qq_profile_dir())
        root = module.project_napcat_root()
        if root is None or not executable.resolve().is_relative_to(root.resolve()):
            raise ValueError('QQ 不在项目 NapCat 安装内，未操作普通 QQ；请检查专用 QQ 路径。')
        return module

    def start(self):
        if not self._lock.acquire(blocking=False):
            raise ValueError('NapCat 正在操作，请稍候。')
        try:
            module = self._module()
            if not module.required_napcat_files() or not module.bot_qq_uin():
                raise ValueError('NapCat 组件或机器人账号配置不完整，请检查原有配置。')
            module.start_napcat_if_needed()
            if not module.project_qq_pids() and not module.napcat_webui_running():
                raise ValueError('NapCat 尚未启动，请查看启动日志。')
            return {'ok': True, 'message': 'NapCat 已启动；登录和连接状态以检测结果为准。'}
        finally:
            self._lock.release()

    def snapshot(self):
        module = self._module()
        ready = module.napcat_webui_running()
        running = bool(module.project_qq_pids())
        return {'phase': 'ready' if ready else 'starting' if self._lock.locked() else
                'running' if running else 'stopped'}

    def stop(self):
        raise ValueError('NapCat 保留 QQ 登录；请通过聊天控制暂停回复，不退出 QQ。')
