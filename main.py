import asyncio
import logging
import random
import json
import os
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8662367369:AAF4uYOO0egA6_Jdkho_q3Nz9EAVU0chdLc"  # <-- Вставь токен бота
ADMIN_ID = 8366926831
CRYPTO_BOT_TOKEN = "554526:AA3lwCzWXKNkEvRNIqoIjm4kIp9JKcWZuJV"
CRYPTO_BOT_API = "https://pay.crypt.bot/api"
DATA_FILE = "data.json"
# =====================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ===================== ХРАНИЛИЩЕ =====================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "products": [],
        "orders": {},
        "users": {},
        "user_ids": {}
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_or_create_user(user_id, username):
    data = load_data()
    uid = str(user_id)
    if uid not in data["users"]:
        fake_id = random.randint(10000000, 99999999)
        data["users"][uid] = {
            "username": username or "Unknown",
            "fake_id": fake_id,
            "balance": 0
        }
        save_data(data)
    else:
        # обновляем username если изменился
        data["users"][uid]["username"] = username or data["users"][uid].get("username", "Unknown")
        save_data(data)
    return data["users"][uid]


# ===================== FSM =====================
class AddProduct(StatesGroup):
    name = State()
    price = State()
    link = State()
    quantity = State()

class EditPrice(StatesGroup):
    choose = State()
    new_price = State()

class Broadcast(StatesGroup):
    text = State()

class BuyProduct(StatesGroup):
    waiting_payment = State()


# ===================== КЛАВИАТУРЫ =====================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Все категории 📚"), KeyboardButton(text="🗂 Наличие товаров 🗂")],
            [KeyboardButton(text="👤 Профиль 👤")]
        ],
        resize_keyboard=True
    )

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add")],
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="admin_edit_price")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="admin_delete")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_list")],
    ])

def products_keyboard(data):
    kb = []
    for i, p in enumerate(data["products"]):
        kb.append([InlineKeyboardButton(
            text=f"{p['name']} | {p['price']} $ | {p['quantity']} шт.",
            callback_data=f"buy_{i}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


# ===================== CRYPTOBOT =====================
async def create_invoice(amount: float, description: str):
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        payload = {
            "asset": "USDT",
            "amount": str(amount),
            "description": description,
            "expires_in": 900
        }
        async with session.post(f"{CRYPTO_BOT_API}/createInvoice", json=payload, headers=headers) as r:
            result = await r.json()
            if result.get("ok"):
                return result["result"]
            return None

async def check_invoice(invoice_id: int):
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        params = {"invoice_ids": invoice_id}
        async with session.get(f"{CRYPTO_BOT_API}/getInvoices", params=params, headers=headers) as r:
            result = await r.json()
            if result.get("ok") and result["result"]["items"]:
                return result["result"]["items"][0]
            return None


# ===================== ХЭНДЛЕРЫ =====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Добро пожаловать!\nПриятных покупок 🛍",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "👤 Профиль 👤")
async def profile(message: Message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        f"❤️ Имя: {user['username']}\n"
        f"🔑 ID: {user['fake_id']}\n"
        f"💰 Ваш баланс: {user['balance']} $"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 История заказов", callback_data="order_history")],
        [InlineKeyboardButton(text="🎟 Активировать купон", callback_data="activate_coupon")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.message(F.text == "🗂 Наличие товаров 🗂")
async def stock(message: Message):
    data = load_data()
    if not data["products"]:
        await message.answer("😔 Товаров пока нет.")
        return
    lines = ["— — — Claude — — —"]
    for p in data["products"]:
        lines.append(f"📄 {p['name']} | {p['price']} $ | {p['quantity']} шт.")
    await message.answer("\n".join(lines))

@dp.message(F.text == "📚 Все категории 📚")
async def categories(message: Message):
    data = load_data()
    if not data["products"]:
        await message.answer("😔 Товаров пока нет.")
        return
    kb = products_keyboard(data)
    await message.answer(
        "📂 Категория: Claude\n📝 Описание:",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(call: CallbackQuery, state: FSMContext):
    data = load_data()
    idx = int(call.data.split("_")[1])
    if idx >= len(data["products"]):
        await call.answer("Товар не найден", show_alert=True)
        return
    product = data["products"][idx]
    if product["quantity"] <= 0:
        await call.answer("Товар закончился!", show_alert=True)
        return

    order_id = random.randint(10000000, 99999999)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    text = (
        f"📄 Товар: {product['name']}\n"
        f"💰 Цена: {product['price']} $\n"
        f"📦 Кол-во: 1 шт.\n"
        f"💡 Заказ: {order_id}\n"
        f"⏰ Время заказа: {now}\n"
        f"⏱ Итоговая сумма: {product['price']} $\n"
        f"💵 Способ оплаты: CryptoBot\n\n"
        f"Для оплаты перейдите по ссылке!\n"
        f"⏰ Время на оплату: 15 минут"
    )

    invoice = await create_invoice(product['price'], f"Заказ #{order_id} — {product['name']}")
    if not invoice:
        await call.message.answer("❌ Ошибка создания счёта. Попробуйте позже.")
        await call.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате ↗", url=invoice["pay_url"])],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{invoice['invoice_id']}_{order_id}_{idx}")]
    ])

    # Сохраняем заказ
    uid = str(call.from_user.id)
    if "orders" not in data:
        data["orders"] = {}
    if uid not in data["orders"]:
        data["orders"][uid] = []
    data["orders"][uid].append({
        "order_id": order_id,
        "product": product["name"],
        "price": product["price"],
        "status": "pending",
        "invoice_id": invoice["invoice_id"],
        "time": now
    })
    save_data(data)

    await call.message.answer(text, reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(call: CallbackQuery):
    parts = call.data.split("_")
    invoice_id = int(parts[1])
    order_id = parts[2]
    product_idx = int(parts[3])

    invoice = await check_invoice(invoice_id)
    if not invoice:
        await call.answer("Ошибка проверки оплаты", show_alert=True)
        return

    if invoice["status"] == "paid":
        data = load_data()
        uid = str(call.from_user.id)

        # Находим заказ и помечаем оплаченным
        for order in data["orders"].get(uid, []):
            if str(order["order_id"]) == order_id:
                if order["status"] == "paid":
                    await call.answer("✅ Уже оплачено! Товар был выдан ранее.", show_alert=True)
                    return
                order["status"] = "paid"
                break

        # Уменьшаем количество и выдаём ссылку
        if product_idx < len(data["products"]):
            product = data["products"][product_idx]
            link = product.get("link", "Ссылка не найдена")
            if product["quantity"] > 0:
                product["quantity"] -= 1
            save_data(data)

            await call.message.answer(
                f"✅ Оплата получена!\n\n"
                f"📦 Ваш товар: {product['name']}\n"
                f"🔗 Ссылка: {link}"
            )
            await call.answer("✅ Оплата подтверждена!", show_alert=True)
        else:
            await call.answer("Ошибка: товар не найден", show_alert=True)
    elif invoice["status"] == "expired":
        data = load_data()
        uid = str(call.from_user.id)
        for order in data["orders"].get(uid, []):
            if str(order["order_id"]) == order_id:
                order["status"] = "cancelled"
        save_data(data)
        await call.answer("❌ Время оплаты истекло. Заказ отменён.", show_alert=True)
        await call.message.answer(f"❌ Заказ: #{order_id} был отменён")
    else:
        await call.answer("⏳ Оплата ещё не получена", show_alert=True)

@dp.callback_query(F.data == "order_history")
async def order_history(call: CallbackQuery):
    data = load_data()
    uid = str(call.from_user.id)
    orders = data["orders"].get(uid, [])
    if not orders:
        await call.answer("У вас нет заказов", show_alert=True)
        return
    lines = ["📋 История заказов:\n"]
    for o in orders[-10:]:
        status_emoji = "✅" if o["status"] == "paid" else ("❌" if o["status"] == "cancelled" else "⏳")
        lines.append(f"{status_emoji} #{o['order_id']} — {o['product']} — {o['price']}$")
    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "activate_coupon")
async def activate_coupon(call: CallbackQuery):
    await call.answer("Функция купонов пока недоступна", show_alert=True)


# ===================== АДМИН =====================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("🔧 Панель администратора:", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin_list")
async def admin_list(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    if not data["products"]:
        await call.answer("Товаров нет", show_alert=True)
        return
    lines = ["📋 Список товаров:\n"]
    for i, p in enumerate(data["products"]):
        lines.append(f"{i}. {p['name']} | {p['price']}$ | {p['quantity']} шт.\n   🔗 {p['link'][:50]}...")
    await call.message.answer("\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "admin_add")
async def admin_add(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    await call.message.answer("📝 Введите название товара:", reply_markup=cancel_keyboard())
    await state.set_state(AddProduct.name)
    await call.answer()

@dp.message(AddProduct.name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("💰 Введите цену в $ (например: 10):", reply_markup=cancel_keyboard())
    await state.set_state(AddProduct.price)

@dp.message(AddProduct.price)
async def add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return
    await state.update_data(price=price)
    await message.answer("🔗 Введите ссылку (товар):", reply_markup=cancel_keyboard())
    await state.set_state(AddProduct.link)

@dp.message(AddProduct.link)
async def add_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.answer("📦 Введите количество (штук):", reply_markup=cancel_keyboard())
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def add_quantity(message: Message, state: FSMContext):
    try:
        qty = int(message.text)
    except ValueError:
        await message.answer("❌ Введите целое число!")
        return
    d = await state.get_data()
    data = load_data()
    data["products"].append({
        "name": d["name"],
        "price": d["price"],
        "link": d["link"],
        "quantity": qty
    })
    save_data(data)
    await message.answer(f"✅ Товар «{d['name']}» добавлен!", reply_markup=main_keyboard())
    await state.clear()

@dp.callback_query(F.data == "admin_edit_price")
async def admin_edit_price(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    if not data["products"]:
        await call.answer("Товаров нет", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{i}. {p['name']} — {p['price']}$", callback_data=f"editprice_{i}")]
        for i, p in enumerate(data["products"])
    ])
    await call.message.answer("Выберите товар для изменения цены:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("editprice_"))
async def editprice_choose(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    idx = int(call.data.split("_")[1])
    await state.update_data(edit_idx=idx)
    await call.message.answer(f"💰 Введите новую цену:", reply_markup=cancel_keyboard())
    await state.set_state(EditPrice.new_price)
    await call.answer()

@dp.message(EditPrice.new_price)
async def editprice_set(message: Message, state: FSMContext):
    try:
        new_price = float(message.text)
    except ValueError:
        await message.answer("❌ Введите число!")
        return
    d = await state.get_data()
    data = load_data()
    data["products"][d["edit_idx"]]["price"] = new_price
    save_data(data)
    await message.answer(f"✅ Цена обновлена: {new_price}$", reply_markup=main_keyboard())
    await state.clear()

@dp.callback_query(F.data == "admin_delete")
async def admin_delete(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    if not data["products"]:
        await call.answer("Товаров нет", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗑 {p['name']}", callback_data=f"delete_{i}")]
        for i, p in enumerate(data["products"])
    ])
    await call.message.answer("Выберите товар для удаления:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("delete_"))
async def delete_product(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    idx = int(call.data.split("_")[1])
    data = load_data()
    if idx < len(data["products"]):
        name = data["products"][idx]["name"]
        data["products"].pop(idx)
        save_data(data)
        await call.message.answer(f"✅ Товар «{name}» удалён.")
    await call.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    await call.message.answer("📢 Введите текст рассылки:", reply_markup=cancel_keyboard())
    await state.set_state(Broadcast.text)
    await call.answer()

@dp.message(Broadcast.text)
async def broadcast_send(message: Message, state: FSMContext):
    data = load_data()
    users = list(data["users"].keys())
    sent = 0
    failed = 0
    for uid in users:
        try:
            await bot.send_message(int(uid), f"📢 Сообщение от магазина:\n\n{message.text}")
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}", reply_markup=main_keyboard())
    await state.clear()

@dp.callback_query(F.data == "cancel")
async def cancel_action(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("❌ Отменено", reply_markup=main_keyboard())
    await call.answer()


# ===================== ЗАПУСК =====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
