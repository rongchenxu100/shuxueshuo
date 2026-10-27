"""Shared single-process search startup, maintenance, and shutdown lifecycle."""

import asyncio
import logging
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from .dev_api import create_search_router
from .repository import SearchRepository

LOGGER = logging.getLogger(__name__)
CLEANUP_INTERVAL = 60
BACKUP_CLEANUP_INTERVAL = 60 * 60


def cleanup_backups(settings):
    from ..product.admin.search_backup import prune_backups
    result = prune_backups(settings)
    if result['failures']:
        LOGGER.error('Search backup cleanup will retry: %s', result['failures'])
    return result


def cleanup_search(repository, settings=None):
    result = {}
    try:
        result.update(repository.cleanup())
    except BaseException:
        if settings is not None:
            try:
                cleanup_backups(settings)
            except Exception:
                LOGGER.exception('Search backup cleanup also failed after live cleanup failed')
        raise
    if settings is not None:
        result['backups'] = cleanup_backups(settings)
    return result


class _SearchMaintenance:
    def __init__(self, repository, settings, *, clock=None):
        self.repository = repository
        self.settings = settings
        self.clock = clock or monotonic
        self.next_backup_cleanup = None

    def cleanup(self):
        try:
            return self.repository.cleanup()
        finally:
            now = self.clock()
            if self.next_backup_cleanup is None or now >= self.next_backup_cleanup:
                self.next_backup_cleanup = now + BACKUP_CLEANUP_INTERVAL
                try:
                    cleanup_backups(self.settings)
                except Exception:
                    LOGGER.exception('Search backup cleanup will retry in one hour')


async def maintain_search(maintenance, stopped):
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=CLEANUP_INTERVAL)
        except TimeoutError:
            try:
                await run_in_threadpool(maintenance.cleanup)
            except Exception:
                LOGGER.exception("Search cleanup will retry")


def install_search(app, *, settings=None, admission_config=None):
    @asynccontextmanager
    async def lifespan(app):
        product = app.state.product
        configured = settings or product.settings
        from ..product.admin.backup import require_restore_complete
        require_restore_complete(configured)
        repository = SearchRepository(
            product.db, configured.root / "work/search/private-v1",
            admission_config=admission_config)
        app.state.search_repository = repository
        app.state.search_drain_path = configured.root / "locks/services-draining"
        app.state.search_accepting = False
        maintenance = _SearchMaintenance(repository, configured)
        await run_in_threadpool(repository.admission.recover)
        await run_in_threadpool(repository.recover)
        await run_in_threadpool(maintenance.cleanup)
        stopped = asyncio.Event()
        cleaner = asyncio.create_task(maintain_search(maintenance, stopped))
        app.state.search_accepting = True
        try:
            yield
        finally:
            app.state.search_accepting = False
            stopped.set()
            await cleaner

    app.include_router(APIRouter(lifespan=lifespan))
    app.include_router(create_search_router(None))
