import asyncio
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


async def handle_payment(
    data: dict, repository: Repository, websocket: websockets.WebSocketServerProtocol
) -> None:
    payment = "PAID" if "paid" in data["payment"] else data["payment"]
    factory_number = data["factory_number"]
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
        cash = data["sales"]["cash"]
        payment_type = data.get("payment_type") or data["sales"].get("payment_type")
        
        if payment_type == "liqpay":
            cash = 0
        elif payment_type == "cash":
            cash = 1
        elif payment_type == "paypass":
            cash = 2
                
        success = await repository.add_fiscalization(
            factory_number=factory_number,
            sales_code=data["sales"]["code"],
            sales_cash=cash,
            created_at=data["sales"]["created_at"],
        )
        message = {"request": "OK"} if success else {"request": "ERROR"}
        await websocket.send(json.dumps(message))


async def handle_input(data: dict, repository: Repository) -> None:
    factory_number = data.get("factory_number")
    chat, place = await repository.get_device_chat_and_place(factory_number)
    if not chat:
        logger.warning(f"Telegram chat wasn't found for {factory_number} device")

    state = "розімкнутий 🔓" if data["input"] == "high" else "замкнутий 🔒"
    await bot_send_message(
        chat, f"Пристрій :{factory_number}\nРозшташування: {place}\n\nСтатус: {state}"
    )
    await asyncio.sleep(2)

