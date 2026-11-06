from __future__ import annotations

import unittest

from atri_qq_bot.qzone.install_webui import install_text, uninstall_text


SOURCE = '''"""routes"""
from src.webui.routers.plugin import router as plugin_router

logger = get_logger("webui.api")
router = APIRouter(prefix="/api/webui")
router.include_router(plugin_router)
'''


class InstallerTests(unittest.TestCase):
    def test_install_is_idempotent_and_uninstall_restores_source(self) -> None:
        installed = install_text(SOURCE)
        self.assertEqual(install_text(installed), installed)
        self.assertIn("router.include_router(qqzone_router)", installed)
        self.assertIn("from plugins.qqzone.webui_router import router", installed)
        self.assertEqual(uninstall_text(installed).strip(), SOURCE.strip())

    def test_upgrade_replaces_old_atri_import_without_duplicate_route(self) -> None:
        old = install_text(SOURCE).replace("plugins.qqzone.webui_router", "atri_qq_bot.qzone.webui_router")
        updated = install_text(old)
        self.assertNotIn("atri_qq_bot", updated)
        self.assertEqual(updated.count("router.include_router(qqzone_router)"), 1)
        self.assertEqual(uninstall_text(updated).strip(), SOURCE.strip())


if __name__ == "__main__":
    unittest.main()
