import asyncio
from logging import Logger, getLogger

from app.bot import bot_send_message
from app.repository import Repository


logger: Logger = getLogger("monitor")


async def device_ping_monitor(
    connections: dict, repository: Repository, ping_interval: int
) -> None:
    while True:
        for fn, ws in connections.copy().items():
            if ws.closed:
                continue

            try:
                pong_waiter = await ws.ping()
                latency = await pong_waiter
                logger.info(f"Pong recieved from {fn} device with {latency} latency")

                await repository.update_device_last_online(fn)
            except Exception:
                pass

        await asyncio.sleep(ping_interval)


async def offline_deivces_monitor(
    offline_devices: dict, repository: Repository, offline_interval: int
) -> None:
    while True:
        devices_and_chats = await repository.get_devices_with_offline_interval(
            offline_interval
        )
        for device, place, chat in devices_and_chats:
            if not chat:
                logger.warning(f"Chat wasn't found for device {device}")
            elif device in offline_devices:
                continue
            else:
                await bot_send_message(
                    chat,
                    f"❌ Пристрій {device}{place} зник з мережі більше {offline_interval} хвилин тому.",
                    device,
                )
                logger.info(f"Adding {device} device to offline_devices")
                offline_devices[device] = chat
                await asyncio.sleep(1)

        await asyncio.sleep(offline_interval * 60)
