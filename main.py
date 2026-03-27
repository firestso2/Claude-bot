import asyncio
import logging
import random
import json
import os
import aiohttp
from datetime import datetime, timedelta
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
BOT_TOKEN = "8662367369:AAF4uYOO0egA6_Jdkho_q3Nz9EAVU0chdLc"           # <-- Вставь токен бота от @BotFather
ADMIN_ID = 8366926831
CRYPTO_BOT_TOKEN = "554526:AA3lwCzWXKNkEvRNIqoIjm4kIp9JKcWZuJV"
CRYPTO_BOT_API = "https://pay.crypt.bot/api"
OWNER_USERNAME = "heksx"
SUPPORT_USERNAME = "ClaudeAiSupport"
DATA_FILE = "data.json"
# =====================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ===================== ХРАНИЛИЩЕ =====================
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "products": [],
        "orders": {},
        "users": {},
        "coupons": {},
        "stats": {"joins": []}
    }

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_or_create_user(user_id: int, username: str) -> dict:
    data = load_data()
    uid = str(user_id)
    is_new = uid not in data["users"]
    if is_new:
        data["users"][uid] = {
            "username": username or "Unknown",
            "balance": 0.0,
            "joined": datetime.now().isoformat()
        }
        if "stats" not in data:
            data["stats"] = {"joins": []}
        data["stats"]["joins"].append(datetime.now().isoformat())
    else:
        data["users"][uid]["username"] = username or data["users"][uid].get("username", "Unknown")
    save_data(data)
    return data["users"][uid]

def parse_links(text: str) -> list:
    links = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit():
            parts = line.split(None, 1)
            if len(parts) == 2:
                prefix = parts[0].rstrip('.)')
                if prefix.isdigit():
                    line = parts[1].strip()
        if line:
            links.append(line)
    return links

def get_stats(data: dict) -> dict:
    now = datetime.now()
    joins = data.get("stats", {}).get("joins", [])
    def count_since(days):
        cutoff = now - timedelta(days=days)
        return sum(1 for j in joins if datetime.fromisoformat(j) >= cutoff)
    return {
        "day": count_since(1),
        "week": count_since(7),
        "month": count_since(30),
        "total": len(data["users"])
    }


# ===================== FSM =====================
class AddProduct(StatesGroup):
    name = State()
    price = State()
    links = State()

class AddLinks(StatesGroup):
    links = State()

class EditPrice(StatesGroup):
    new_price = State()

class Broadcast(StatesGroup):
    text = State()

class ActivateCoupon(StatesGroup):
    code = State()

class CreateCoupon(StatesGroup):
    code = State()
    amount = State()
    max_uses = State()
    expire_days = State()


# ===================== КЛАВИАТУРЫ =====================
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 Товары"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="📦 Мои покупки"), KeyboardButton(text="⭐ Репутация")],
            [KeyboardButton(text="❓ FAQ"), KeyboardButton(text="📞 Поддержка и контакты")]
        ],
        resize_keyboard=True
    )

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар",          callback_data="admin_add")],
        [InlineKeyboardButton(text="🔗 Добавить ссылки в товар", callback_data="admin_addlinks")],
        [InlineKeyboardButton(text="✏️ Изменить цену",           callback_data="admin_edit_price")],
        [InlineKeyboardButton(text="🗑 Удалить товар",           callback_data="admin_delete")],
        [InlineKeyboardButton(text="📢 Рассылка",               callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📋 Список товаров",          callback_data="admin_list")],
        [InlineKeyboardButton(text="🎟 Управление купонами",     callback_data="admin_coupons")],
        [InlineKeyboardButton(text="📊 Статистика",              callback_data="admin_stats")],
    ])

def coupon_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать купон",   callback_data="coupon_create")],
        [InlineKeyboardButton(text="📋 Список купонов", callback_data="coupon_list")],
        [InlineKeyboardButton(text="🗑 Удалить купон",  callback_data="coupon_delete")],
        [InlineKeyboardButton(text="◀️ Назад",          callback_data="back_admin")],
    ])

def products_keyboard(data: dict):
    kb = []
    for i, p in enumerate(data["products"]):
        qty = len(p.get("links", []))
        kb.append([InlineKeyboardButton(
            text=f"{p['name']} | {p['price']} $ | {qty} шт.",
            callback_data=f"buy_{i}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def support_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👔 Связь с владельцем ↗", url=f"https://t.me/{OWNER_USERNAME}")],
        [InlineKeyboardButton(text="🔧 Связь с поддержкой ↗",  url=f"https://t.me/{SUPPORT_USERNAME}")]
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
            return result["result"] if result.get("ok") else None

async def check_invoice(invoice_id: int):
    async with aiohttp.ClientSession() as session:
        headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
        params = {"invoice_ids": invoice_id}
        async with session.get(f"{CRYPTO_BOT_API}/getInvoices", params=params, headers=headers) as r:
            result = await r.json()
            if result.get("ok") and result["result"]["items"]:
                return result["result"]["items"][0]
            return None


# ===================== ОСНОВНЫЕ ХЭНДЛЕРЫ =====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_or_create_user(message.from_user.id, message.from_user.username)
    await message.answer("👋 Добро пожаловать!\nПриятных покупок 🛍", reply_markup=main_keyboard())


# ---------- Профиль ----------
@dp.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    balance = user.get("balance", 0.0)
    uname = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    text = (
        f"❤️ Имя: {uname}\n"
        f"🔑 ID: {message.from_user.id}\n"
        f"💰 Ваш баланс: {balance:.2f} $\n\n"
        f"<i>Баланс используется как скидка при следующей покупке.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 История заказов",    callback_data="order_history")],
        [InlineKeyboardButton(text="🎟 Активировать купон", callback_data="use_coupon")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ---------- Активация купона ----------
@dp.callback_query(F.data == "use_coupon")
async def use_coupon_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🎟 Введите код купона:", reply_markup=cancel_keyboard())
    await state.set_state(ActivateCoupon.code)
    await call.answer()

@dp.message(ActivateCoupon.code)
async def use_coupon_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    data = load_data()
    uid = str(message.from_user.id)
    coupons = data.get("coupons", {})

    if code not in coupons:
        await message.answer("❌ Купон не найден.")
        await state.clear()
        return

    coupon = coupons[code]

    if coupon.get("expire_at") and datetime.now() > datetime.fromisoformat(coupon["expire_at"]):
        await message.answer("❌ Срок действия купона истёк.")
        await state.clear()
        return

    used_by = coupon.get("used_by", [])
    max_uses = coupon.get("max_uses", 0)

    if uid in used_by:
        await message.answer("❌ Вы уже использовали этот купон.")
        await state.clear()
        return

    if max_uses > 0 and len(used_by) >= max_uses:
        await message.answer("❌ Лимит активаций купона исчерпан.")
        await state.clear()
        return

    amount = coupon["amount"]
    data["users"][uid]["balance"] = round(data["users"][uid].get("balance", 0.0) + amount, 2)
    coupon["used_by"].append(uid)
    save_data(data)

    await message.answer(
        f"✅ Купон активирован!\n💰 На ваш баланс начислено: <b>{amount:.2f} $</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )
    await state.clear()


# ---------- Мои покупки ----------
@dp.message(F.text == "📦 Мои покупки")
async def my_purchases(message: Message):
    data = load_data()
    uid = str(message.from_user.id)
    orders = [o for o in data["orders"].get(uid, []) if o["status"] == "paid"]
    if not orders:
        await message.answer("😔 У вас пока нет завершённых покупок.")
        return
    lines = ["✅ Ваши покупки:\n"]
    for o in orders[-15:]:
        lines.append(f"• #{o['order_id']} — {o['product']} — {o['price']}$ ({o['time']})")
    await message.answer("\n".join(lines))


# ---------- Репутация ----------
@dp.message(F.text == "⭐ Репутация")
async def reputation(message: Message):
    await message.answer("⭐ Система репутации\n\nПока что у вас нет отзывов.")


# ---------- FAQ ----------
@dp.message(F.text == "❓ FAQ")
async def faq(message: Message):
    await message.answer(
        "❓ <b>Часто задаваемые вопросы</b>\n\n"
        "• <b>Как купить товар?</b>\nНажми «Товары», выбери нужный, оплати через CryptoBot. После оплаты ссылка выдаётся автоматически.\n\n"
        "• <b>Какая валюта оплаты?</b>\nUSDT через CryptoBot.\n\n"
        "• <b>Что такое баланс?</b>\nБаланс начисляется через купоны и применяется как скидка при следующей покупке автоматически.\n\n"
        "• <b>Не получил товар после оплаты?</b>\nНажми «Проверить оплату» или обратись в поддержку.\n\n"
        "• <b>Сколько ждать ответа поддержки?</b>\nДо 12 часов.\n\n"
        "• <b>Покупка от 5 штук?</b>\nПри заказе от 5 штук готовы идти на гарантов — пишите владельцу @heksx.",
        parse_mode="HTML"
    )


# ---------- Поддержка ----------
@dp.message(F.text == "📞 Поддержка и контакты")
async def support(message: Message):
    text = (
        "🛠 <b>Поддержка и контакты</b>\n\n"
        "Выберите, по какому вопросу хотите связаться:\n\n"
        "• По вопросам сотрудничества, рекламы или других бизнес-предложений — кнопка «Связь с владельцем».\n\n"
        "• По техническим проблемам с оплатой, получением товара или работой с инструкцией — кнопка «Связь с поддержкой».\n\n"
        "⏰ Среднее время ответа: до 12 часов.\n"
        "🕐 Часы работы: с 18:00 до 00:00 (МСК), ежедневно.\n\n"
        "📦 При покупке от 5 штук готовы идти на гарантов — пишите владельцу @heksx."
    )
    await message.answer(text, reply_markup=support_keyboard(), parse_mode="HTML")


# ---------- Товары ----------
@dp.message(F.text == "🛒 Товары")
async def categories(message: Message):
    data = load_data()
    if not data["products"]:
        await message.answer("😔 Товаров пока нет.")
        return
    kb = products_keyboard(data)
    lines = ["— — — 🛒 Товары — — —\n"]
    for p in data["products"]:
        qty = len(p.get("links", []))
        lines.append(f"📄 {p['name']} | {p['price']} $ | {qty} шт.")
    await message.answer("\n".join(lines), reply_markup=kb)


# ---------- Покупка ----------
@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(call: CallbackQuery):
    data = load_data()
    idx = int(call.data.split("_")[1])
    if idx >= len(data["products"]):
        await call.answer("Товар не найден", show_alert=True)
        return
    product = data["products"][idx]
    qty = len(product.get("links", []))
    if qty <= 0:
        await call.answer("😔 Товар закончился!", show_alert=True)
        return

    uid = str(call.from_user.id)
    user = data["users"].get(uid, {})
    balance = user.get("balance", 0.0)
    price = product["price"]
    discount = round(min(balance, price), 2)
    pay_amount = round(price - discount, 2)

    order_id = random.randint(10000000, 99999999)
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    deadline = (now + timedelta(minutes=15)).strftime("%H:%M")

    # Полностью покрывается балансом
    if pay_amount <= 0:
        data["users"][uid]["balance"] = round(balance - price, 2)
        link = product["links"].pop(0)
        if uid not in data["orders"]:
            data["orders"][uid] = []
        data["orders"][uid].append({
            "order_id": order_id, "product": product["name"],
            "price": price, "paid_amount": 0, "discount": price,
            "status": "paid", "time": now_str
        })
        save_data(data)
        await call.message.answer(
            f"✅ <b>Оплачено с баланса!</b>\n\n"
            f"📦 Товар: {product['name']}\n"
            f"💰 Списано с баланса: {price} $\n"
            f"🔗 Ссылка: {link}",
            parse_mode="HTML"
        )
        try:
            uname = f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id)
            await bot.send_message(
                ADMIN_ID,
                f"🛒 <b>Новая покупка!</b>\n\n"
                f"👤 Пользователь: {uname} (ID: {call.from_user.id})\n"
                f"📦 Товар: {product['name']}\n"
                f"💰 Цена: {price} $\n"
                f"🎟 Оплачено полностью с баланса\n"
                f"🔢 Заказ: #{order_id}\n"
                f"🕐 Время: {now_str}",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await call.answer()
        return

    invoice = await create_invoice(pay_amount, f"Заказ #{order_id} — {product['name']}")
    if not invoice:
        await call.message.answer("❌ Ошибка создания счёта. Попробуйте позже.")
        await call.answer()
        return

    discount_line = f"\n🎟 <b>Скидка с баланса:</b> -{discount:.2f} $" if discount > 0 else ""
    text = (
        f"📄 <b>Товар:</b> {product['name']}\n"
        f"💰 <b>Цена:</b> {price} $"
        f"{discount_line}\n"
        f"💵 <b>К оплате:</b> {pay_amount} $\n"
        f"📦 <b>Кол-во:</b> 1 шт.\n"
        f"💡 <b>Заказ:</b> {order_id}\n"
        f"⏰ <b>Время заказа:</b> {now_str}\n"
        f"💵 <b>Способ оплаты:</b> CryptoBot\n\n"
        f"Для оплаты перейдите по ссылке!\n"
        f"⏰ <b>Время на оплату:</b> 15 минут\n"
        f"🕐 Необходимо оплатить до {deadline}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате ↗", url=invoice["pay_url"])],
        [InlineKeyboardButton(text="✅ Проверить оплату",
                              callback_data=f"check_{invoice['invoice_id']}_{order_id}_{idx}_{int(discount*100)}")]
    ])

    if uid not in data["orders"]:
        data["orders"][uid] = []
    data["orders"][uid].append({
        "order_id": order_id, "product": product["name"],
        "price": price, "paid_amount": pay_amount, "discount": discount,
        "status": "pending", "invoice_id": invoice["invoice_id"],
        "product_idx": idx, "time": now_str
    })
    save_data(data)
    await call.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# ---------- Проверка оплаты ----------
@dp.callback_query(F.data.startswith("check_"))
async def check_payment(call: CallbackQuery):
    parts = call.data.split("_")
    invoice_id = int(parts[1])
    order_id = parts[2]
    product_idx = int(parts[3])
    discount = int(parts[4]) / 100 if len(parts) > 4 else 0.0

    invoice = await check_invoice(invoice_id)
    if not invoice:
        await call.answer("Ошибка проверки оплаты", show_alert=True)
        return

    if invoice["status"] == "paid":
        data = load_data()
        uid = str(call.from_user.id)

        target_order = next((o for o in data["orders"].get(uid, []) if str(o["order_id"]) == order_id), None)
        if not target_order:
            await call.answer("Заказ не найден", show_alert=True)
            return
        if target_order["status"] == "paid":
            await call.answer("✅ Уже оплачено! Товар выдан ранее.", show_alert=True)
            return
        if product_idx >= len(data["products"]):
            await call.answer("Ошибка: товар не найден", show_alert=True)
            return

        product = data["products"][product_idx]
        links = product.get("links", [])
        if not links:
            await call.answer("😔 Товар закончился. Обратитесь в поддержку.", show_alert=True)
            return

        link = links.pop(0)
        product["links"] = links
        target_order["status"] = "paid"

        if discount > 0:
            data["users"][uid]["balance"] = round(max(0, data["users"][uid].get("balance", 0.0) - discount), 2)

        save_data(data)

        await call.message.answer(
            f"✅ <b>Оплата получена!</b>\n\n"
            f"📦 Товар: {product['name']}\n"
            f"🔗 Ссылка: {link}",
            parse_mode="HTML"
        )
        await call.answer("✅ Оплата подтверждена!", show_alert=True)

        # Уведомление админу
        try:
            uname = f"@{call.from_user.username}" if call.from_user.username else str(call.from_user.id)
            await bot.send_message(
                ADMIN_ID,
                f"🛒 <b>Новая покупка!</b>\n\n"
                f"👤 Пользователь: {uname} (ID: {call.from_user.id})\n"
                f"📦 Товар: {product['name']}\n"
                f"💰 Цена: {target_order['price']} $\n"
                f"💳 Оплачено крипто: {target_order.get('paid_amount', target_order['price'])} $\n"
                + (f"🎟 Скидка с баланса: {discount:.2f} $\n" if discount > 0 else "") +
                f"🔢 Заказ: #{order_id}\n"
                f"🕐 Время: {target_order['time']}",
                parse_mode="HTML"
            )
        except Exception:
            pass

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


# ---------- История заказов ----------
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
        emoji = "✅" if o["status"] == "paid" else ("❌" if o["status"] == "cancelled" else "⏳")
        lines.append(f"{emoji} #{o['order_id']} — {o['product']} — {o['price']}$")
    await call.message.answer("\n".join(lines))
    await call.answer()


# ===================== ПАНЕЛЬ АДМИНИСТРАТОРА =====================

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("🔧 Панель администратора:", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "back_admin")
async def back_admin(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    await call.message.answer("🔧 Панель администратора:", reply_markup=admin_keyboard())
    await call.answer()


# ---------- Статистика ----------
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    s = get_stats(data)
    total_revenue = sum(
        o.get("paid_amount", o.get("price", 0))
        for uid_orders in data["orders"].values()
        for o in uid_orders if o["status"] == "paid"
    )
    await call.message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Новых пользователей:\n"
        f"  • За день: <b>{s['day']}</b>\n"
        f"  • За неделю: <b>{s['week']}</b>\n"
        f"  • За месяц: <b>{s['month']}</b>\n"
        f"  • Всего: <b>{s['total']}</b>\n\n"
        f"💰 Выручка (оплачено крипто): <b>{total_revenue:.2f} $</b>",
        parse_mode="HTML"
    )
    await call.answer()


# ---------- Список товаров ----------
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
        qty = len(p.get("links", []))
        lines.append(f"{i}. {p['name']} | {p['price']}$ | {qty} шт.")
        for j, lnk in enumerate(p.get("links", [])[:3], 1):
            lines.append(f"   {j}. {lnk[:60]}")
        if qty > 3:
            lines.append(f"   ... ещё {qty - 3} шт.")
        lines.append("")
    await call.message.answer("\n".join(lines))
    await call.answer()


# ---------- Добавить товар ----------
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
    await message.answer(
        "🔗 Введите ссылки нумерованным списком:\n\n"
        "1. https://claude.ai/...\n2. https://claude.ai/...",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(AddProduct.links)

@dp.message(AddProduct.links)
async def add_links_handler(message: Message, state: FSMContext):
    links = parse_links(message.text)
    if not links:
        await message.answer("❌ Не удалось распознать ссылки. Попробуйте ещё раз:")
        return
    d = await state.get_data()
    data = load_data()
    data["products"].append({"name": d["name"], "price": d["price"], "links": links})
    save_data(data)
    await message.answer(f"✅ Товар «{d['name']}» добавлен!\n📦 Количество: {len(links)} шт.", reply_markup=main_keyboard())
    await state.clear()


# ---------- Добавить ссылки в товар ----------
@dp.callback_query(F.data == "admin_addlinks")
async def admin_addlinks(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    if not data["products"]:
        await call.answer("Товаров нет", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{p['name']} ({len(p.get('links',[]))} шт.)", callback_data=f"addlinks_{i}")]
        for i, p in enumerate(data["products"])
    ])
    await call.message.answer("Выберите товар:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("addlinks_"))
async def addlinks_choose(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    idx = int(call.data.split("_")[1])
    await state.update_data(addlinks_idx=idx)
    await call.message.answer("🔗 Введите новые ссылки нумерованным списком:", reply_markup=cancel_keyboard())
    await state.set_state(AddLinks.links)
    await call.answer()

@dp.message(AddLinks.links)
async def addlinks_save(message: Message, state: FSMContext):
    new_links = parse_links(message.text)
    if not new_links:
        await message.answer("❌ Не удалось распознать ссылки.")
        return
    d = await state.get_data()
    data = load_data()
    idx = d["addlinks_idx"]
    data["products"][idx]["links"].extend(new_links)
    total = len(data["products"][idx]["links"])
    save_data(data)
    await message.answer(f"✅ Добавлено {len(new_links)} ссылок! Итого: {total} шт.", reply_markup=main_keyboard())
    await state.clear()


# ---------- Изменить цену ----------
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
        [InlineKeyboardButton(text=f"{p['name']} — {p['price']}$", callback_data=f"editprice_{i}")]
        for i, p in enumerate(data["products"])
    ])
    await call.message.answer("Выберите товар:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("editprice_"))
async def editprice_choose(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    idx = int(call.data.split("_")[1])
    await state.update_data(edit_idx=idx)
    await call.message.answer("💰 Введите новую цену:", reply_markup=cancel_keyboard())
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


# ---------- Удалить товар ----------
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


# ---------- Рассылка ----------
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
    sent, failed = 0, 0
    for uid in users:
        try:
            await bot.send_message(int(uid), message.text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"✅ Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}", reply_markup=main_keyboard())
    await state.clear()


# ===================== КУПОНЫ (АДМИН) =====================

@dp.callback_query(F.data == "admin_coupons")
async def admin_coupons(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    await call.message.answer("🎟 Управление купонами:", reply_markup=coupon_admin_keyboard())
    await call.answer()

# -- Создать купон --
@dp.callback_query(F.data == "coupon_create")
async def coupon_create_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    await call.message.answer(
        "🎟 Введите код купона (латиница/цифры, например: PROMO2025):",
        reply_markup=cancel_keyboard()
    )
    await state.set_state(CreateCoupon.code)
    await call.answer()

@dp.message(CreateCoupon.code)
async def coupon_set_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    data = load_data()
    if code in data.get("coupons", {}):
        await message.answer("❌ Такой купон уже существует. Введите другой код:")
        return
    await state.update_data(code=code)
    await message.answer("💰 Введите сумму начисления в $ (например: 5):", reply_markup=cancel_keyboard())
    await state.set_state(CreateCoupon.amount)

@dp.message(CreateCoupon.amount)
async def coupon_set_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число!")
        return
    await state.update_data(amount=amount)
    await message.answer(
        "🔢 Введите максимальное количество активаций:\n<i>0 = безлимит</i>",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await state.set_state(CreateCoupon.max_uses)

@dp.message(CreateCoupon.max_uses)
async def coupon_set_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число ≥ 0!")
        return
    await state.update_data(max_uses=max_uses)
    await message.answer(
        "📅 Введите срок действия в днях:\n<i>0 = без срока</i>",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await state.set_state(CreateCoupon.expire_days)

@dp.message(CreateCoupon.expire_days)
async def coupon_set_expire(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        if days < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число ≥ 0!")
        return
    d = await state.get_data()
    data = load_data()
    if "coupons" not in data:
        data["coupons"] = {}

    expire_at = (datetime.now() + timedelta(days=days)).isoformat() if days > 0 else None

    data["coupons"][d["code"]] = {
        "amount": d["amount"],
        "max_uses": d["max_uses"],
        "expire_at": expire_at,
        "used_by": []
    }
    save_data(data)

    limits = f"{d['max_uses']} активаций" if d["max_uses"] > 0 else "безлимит"
    expiry = f"{days} дн." if days > 0 else "без срока"
    await message.answer(
        f"✅ Купон создан!\n\n"
        f"🎟 Код: <b>{d['code']}</b>\n"
        f"💰 Сумма: <b>{d['amount']} $</b>\n"
        f"🔢 Активаций: <b>{limits}</b>\n"
        f"📅 Срок: <b>{expiry}</b>",
        parse_mode="HTML", reply_markup=main_keyboard()
    )
    await state.clear()

# -- Список купонов --
@dp.callback_query(F.data == "coupon_list")
async def coupon_list(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    coupons = data.get("coupons", {})
    if not coupons:
        await call.answer("Купонов нет", show_alert=True)
        return
    now = datetime.now()
    lines = ["📋 <b>Купоны:</b>\n"]
    for code, c in coupons.items():
        uses = len(c.get("used_by", []))
        max_u = c.get("max_uses", 0)
        limit_str = f"{uses}/{max_u}" if max_u > 0 else f"{uses}/∞"
        expired = ""
        if c.get("expire_at"):
            if now > datetime.fromisoformat(c["expire_at"]):
                expired = " ❌ просрочен"
            else:
                left = (datetime.fromisoformat(c["expire_at"]) - now).days
                expired = f" (ещё {left} дн.)"
        lines.append(f"• <b>{code}</b> — {c['amount']}$ — {limit_str} акт.{expired}")
    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()

# -- Удалить купон --
@dp.callback_query(F.data == "coupon_delete")
async def coupon_delete_list(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    data = load_data()
    coupons = data.get("coupons", {})
    if not coupons:
        await call.answer("Купонов нет", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗑 {code} ({c['amount']}$)", callback_data=f"delcoupon_{code}")]
        for code, c in coupons.items()
    ])
    await call.message.answer("Выберите купон для удаления:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("delcoupon_"))
async def coupon_delete_confirm(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔", show_alert=True)
        return
    code = call.data.split("_", 1)[1]
    data = load_data()
    if code in data.get("coupons", {}):
        del data["coupons"][code]
        save_data(data)
        await call.message.answer(f"✅ Купон <b>{code}</b> удалён.", parse_mode="HTML")
    await call.answer()


# ---------- Отмена ----------
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
