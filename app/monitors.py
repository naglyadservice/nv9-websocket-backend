import asyncio
from logging import Logger, getLogger

from app.bot import bot_send_message
from app.repository import Repository


logger: Logger = getLogger("monitor")


async def device_ping_monitor(
    connections: dict, repository: Repository, ping_interval: int, offline_devices: dict
) -> None:
    while True:
        for factory_number, websocket in list(connections.items()):
            if websocket.closed:
                continue

            try:
                pong_waiter = await websocket.ping()
                latency = await pong_waiter
                logger.info(f"Pong recieved from {factory_number} device with {latency} latency")
                await repository.update_device_last_online(factory_number)
            except Exception:
                pass
            else:    
                if factory_number in offline_devices:
                    chat, place = offline_devices.get(factory_number)
                    await bot_send_message(
                        chat,
                        f"Пристрій: {factory_number}\nРозташування: {place}\n\nСтатус: у мережі ✅",
                        factory_number,
                    )
                    offline_devices.pop(factory_number)
                    await asyncio.sleep(2)

        await asyncio.sleep(ping_interval)


async def offline_deivces_monitor(
    offline_devices: dict, repository: Repository, offline_interval: int
) -> None:
    while True:
        devices_and_chats = await repository.get_devices_with_offline_interval(
            offline_interval
        )
        for device, place, last_online, chat in devices_and_chats:
            if device in offline_devices or not chat:
                continue
            else:
                await bot_send_message(
                    chat,
                    f"Пристрій: {device}\nРозташування: {place}\n\nСтатус: зник з мережі в {last_online} ❌",
                    device,
                )
                logger.info(f"Adding {device} device to offline_devices")
                offline_devices[device] = (chat, place)
                await asyncio.sleep(2)

        await asyncio.sleep(120)
