from arq.connections import RedisSettings
from app.config import settings


async def startup(ctx: dict) -> None:
    """Called when the worker starts. Initialize shared resources."""
    pass


async def shutdown(ctx: dict) -> None:
    """Called when the worker shuts down. Clean up shared resources."""
    pass


class WorkerSettings:
    functions = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
