import logging

from app.adapters.registry import AdapterRegistry
from app.db.interface import IAgentDatabase
from app.plugins.actions import PluginActionDispatcher
from app.models.domain import PluginStatus
from app.plugins.catalog import PluginCatalog
from app.plugins.events import PluginEvent, PluginEventBus
from app.plugins.registry import PluginRunnerRegistry


logger = logging.getLogger("augentia.plugins.service")
_ACTIVE_STATUSES = {
    PluginStatus.STARTING,
    PluginStatus.WAITING_INPUT,
    PluginStatus.RUNNING,
    PluginStatus.STOPPING,
}


def register_plugin_event_delivery(
    event_bus: PluginEventBus,
    db: IAgentDatabase,
    registry: PluginRunnerRegistry,
    catalog: PluginCatalog,
) -> None:
    async def deliver(event: PluginEvent) -> None:
        for instance in await db.list_plugin_instances():
            if instance.status != PluginStatus.RUNNING:
                continue
            try:
                definition = catalog.get(instance.plugin_id)
            except KeyError:
                continue
            if event.type not in definition.subscriptions:
                continue
            runner = registry.get(instance.id)
            if runner is not None and runner.is_running:
                await runner.send_event(event)

    event_bus.subscribe(deliver)


async def recover_interrupted_plugin_runs(db: IAgentDatabase) -> None:
    """Mark stale active runs as errored after a backend restart."""
    for instance in await db.list_plugin_instances():
        if instance.status not in _ACTIVE_STATUSES:
            continue
        if instance.current_run_id:
            try:
                await db.update_plugin_run(
                    instance.current_run_id,
                    status=PluginStatus.ERRORED,
                    error="backend restarted while plugin was running",
                )
            except KeyError:
                logger.warning(
                    "plugin instance %s referenced missing run %s during recovery",
                    instance.id,
                    instance.current_run_id,
                )
        await db.update_plugin_instance(instance.id, status=PluginStatus.ERRORED)


async def auto_start_plugin_instances(
    db: IAgentDatabase,
    registry: PluginRunnerRegistry,
    catalog: PluginCatalog,
    session_registry: AdapterRegistry,
) -> None:
    for instance in await db.list_plugin_instances():
        if not instance.auto_start:
            continue
        try:
            definition = catalog.get(instance.plugin_id)
            dispatcher = PluginActionDispatcher(db, session_registry)
            runner = registry.get_or_create(instance.id, db, dispatcher)
            if not runner.is_running:
                await runner.start(definition, instance)
        except Exception as e:
            logger.exception("failed to auto-start plugin instance %s", instance.id)
            try:
                await db.update_plugin_instance(instance.id, status=PluginStatus.ERRORED)
            except Exception:
                logger.exception("failed to mark plugin instance %s errored", instance.id)


async def stop_running_plugin_instances(
    db: IAgentDatabase,
    registry: PluginRunnerRegistry,
) -> None:
    for instance in await db.list_plugin_instances():
        runner = registry.get(instance.id)
        if runner is not None and runner.is_running:
            await runner.stop()
