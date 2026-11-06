"""Claim each incoming event once before generation or outward delivery.

An interrupted/uncertain send stays claimed across restarts. This is deliberate:
the framework cannot know whether a platform accepted an interrupted request.
"""
from contextlib import contextmanager
from hashlib import sha256
import asyncio
import json
import logging
from pathlib import Path
import sqlite3


# Terminal/observable outcomes. ``unknown`` and ``core_failed`` are never
# retried automatically; ``skipped`` records a deliberate no-send decision
# (auto-send off, rate limited) so a poller will not reconsider it forever.
STATES = {'claimed', 'submitted', 'unknown', 'core_failed', 'skipped'}


class DeliveryLedger:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS delivery (id TEXT PRIMARY KEY, fingerprint TEXT, state TEXT)')
                yield db
        finally:
            db.close()

    @staticmethod
    def key(event):
        fields = [event.platform, event.account_id, event.kind, event.conversation_id, event.actor_id, event.event_id]
        return sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()

    def seen(self, event) -> bool:
        """True if this event was ever claimed (handy for poll-based sources)."""
        with self._db() as db:
            return db.execute('SELECT 1 FROM delivery WHERE id=?', (self.key(event),)).fetchone() is not None

    def claim(self, event):
        key = self.key(event)
        fingerprint = sha256(json.dumps(event.payload(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint FROM delivery WHERE id=?', (key,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ValueError('同一平台事件的内容已变化')
                return False
            db.execute('INSERT INTO delivery VALUES (?,?,?)', (key, fingerprint, 'claimed'))
        return True

    def mark(self, event, state):
        if state not in STATES:
            raise ValueError('无效的交付状态')
        with self._db() as db:
            db.execute('UPDATE delivery SET state=? WHERE id=?', (state, self.key(event)))

    def state_of(self, event) -> str:
        """Current stored state, or empty string if never claimed."""
        with self._db() as db:
            row = db.execute('SELECT state FROM delivery WHERE id=?', (self.key(event),)).fetchone()
        return row[0] if row else ''


class DeliveryPipeline:
    """The one place that turns an event into exactly one delivered reply.

    Platforms differ only in how they arrive (push vs poll) and how they send
    (a receipt vs UI automation). Everything between — generate once, send
    once, record the outcome — is shared. QQ's AstrBot bridge calls :meth:`run`;
    a polling channel claims first and then calls :meth:`deliver`.
    """

    def __init__(self, ledger: DeliveryLedger, core, *, logger: logging.Logger | None = None):
        self.ledger = ledger
        self.core = core
        self.logger = logger or logging.getLogger("atri-platform")

    async def run(self, event, send) -> str:
        """Claim, generate, send, record. Returns ``duplicate`` or ``submitted``."""
        if not await asyncio.to_thread(self.ledger.claim, event):
            return 'duplicate'
        return await self.deliver(event, send)

    async def deliver(self, event, send) -> str:
        """Generate + send for an event the caller has already claimed.

        Errors propagate unchanged so each caller keeps its own error contract
        (the QQ bridge re-raises a TimeoutError; a poller inspects the ledger).
        The ledger state still records whether generation or send failed.
        """
        try:
            result = await self.core.chat(event)
        except Exception:
            await asyncio.to_thread(self.ledger.mark, event, 'core_failed')
            raise
        reply = str((result or {}).get('reply') or '').strip()
        if not reply:
            await asyncio.to_thread(self.ledger.mark, event, 'core_failed')
            raise ValueError('核心未返回完整回复')
        try:
            await send(reply)
        except BaseException:
            # Cancellation/timeout after send began has an unknown outcome.
            await asyncio.to_thread(self.ledger.mark, event, 'unknown')
            raise
        await asyncio.to_thread(self.ledger.mark, event, 'submitted')
        return 'submitted'
