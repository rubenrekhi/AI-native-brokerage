from arq.connections import RedisSettings
from arq.cron import cron
from app.config import settings
from app.tasks.health_ping import health_ping


async def startup(ctx: dict) -> None:
    """Called when the worker starts. Initialize shared resources."""
    pass


async def shutdown(ctx: dict) -> None:
    """Called when the worker shuts down. Clean up shared resources."""
    pass


class WorkerSettings:
    functions = [health_ping]
    cron_jobs = [cron(health_ping, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
