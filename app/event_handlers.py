import json
from logging import Logger, getLogger
import websockets

from app.bot import bot_send_message
from app.repository import Repository


logger: Logger = getLogger("handlers")


async def handle_hello_msg(
    data: dict,
    connections: dict,
    websocket: websockets.WebSocketServerProtocol,
    offline_devices: dict,
) -> None:
    factory_number = data["my_factory_number"]
    connections[factory_number] = websocket
    logger.info(f"Hello from {factory_number}")
    if factory_number in offline_devices:
        await bot_send_message(
            offline_devices[factory_number],
            f"✅ Пристрій {factory_number} знов у мережі.",
            factory_number,
        )
        offline_devices.pop(factory_number)


async def handle_payment(
    data: dict, repository: Repository, websocket: websockets.WebSocketServerProtocol
) -> None:
    factory_number = data["factory_number"]
    payment = data["payment"]
    logger.info(f"Payment for {factory_number} is {payment}")

    await repository.update_system_message_response(payment, factory_number)
    await websocket.send(json.dumps({"request": "OK"}))


async def handle_fiscalization(
    data: dict, repository: Repository, websocket: websockets.WebSocketServerProtocol
) -> None:
    factory_number = data["factory_number"]
    logger.info(f"Fiscalization from {factory_number}. Amount: {data['sales']['cash']}")
    if await repository.check_recent_fiscalization(
        factory_number, data["sales"]["code"], 1
    ):
        logger.warning(f"Duplicated fiscalization for {factory_number} device")
        await websocket.send(
            json.dumps({"request": "ERROR", "message": "Duplicated fiscalization"})
        )
    else:
        if await repository.add_fiscalization(
            factory_number,
            data["sales"]["code"],
            data["sales"]["cash"],
            data["sales"]["created_at"],
        ):
            await websocket.send(json.dumps({"request": "OK"}))
        else:
            await websocket.send(json.dumps({"request": "ERROR"}))


async def handle_input(data: dict, repository: Repository) -> None:
    factory_number = data.get("factory_number")
    chat = await repository.get_tg_chat_by_device(factory_number)
    if not chat:
        logger.warning(f"Telegram chat wasn't found for {factory_number} device")

    state = "розімкнутий 🔓" if data["input"] == "high" else "замкнутий 🔒"
    await bot_send_message(chat, f"Вхід пристрою:{factory_number} {state}")
