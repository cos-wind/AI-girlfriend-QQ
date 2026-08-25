from __future__ import annotations

import unittest

from plugins.qqzone.install_webui import install_text, uninstall_text


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
        self.assertEqual(uninstall_text(installed).strip(), SOURCE.strip())


if __name__ == "__main__":
    unittest.main()
