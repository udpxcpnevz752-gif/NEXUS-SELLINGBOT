import logging
import sqlite3
import random
import string
import os
import httpx
import html
import io
import qrcode
import asyncio
import sys
from datetime import datetime

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DATABASE_URL = os.getenv("DATABASE_URL")

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# === MONKEY PATCH FOR BOT API 9.4+ CUSTOM EMOJI ON BUTTONS ===
original_to_dict = InlineKeyboardButton.to_dict

def custom_to_dict(self, *args, **kwargs):
    d = original_to_dict(self, *args, **kwargs)
    if 'text' in d and '||emoji:' in d['text']:
        parts = d['text'].split('||emoji:')
        d['text'] = parts[0]
        d['icon_custom_emoji_id'] = parts[1]
    return d

InlineKeyboardButton.to_dict = custom_to_dict
# ==============================================================

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("nexus_max.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- CONFIG ---
TOKEN = "8203606211:AAGNWwowtjnPMoI5uxo6Pt5j7a_5-srfCAo"
ADMIN_ID = 7529580444
DB_NAME = "nexus_bot.db"
BINANCE_ID = "1129378736"
USDT_BEP20_ADDRESS = "0xfaa43c4c6e783b740470306fd18e4db3ab7824ad"
UPI_ID = "begumop@fam"
ADMIN_BOT_TOKEN = "8725003968:AAHnPLZWjoCsIPt4hKYEmzQmLkkRBogVBnQ"
USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
MY_WALLET = "0xfaa43c4c6e783b740470306fd18e4db3ab7824ad"

from db import db_query, init_db, get_db_conn, DATABASE_URL, DB_NAME

# State for ConversationHandler
WAIT_AMOUNT = 1
WAIT_TXID = 2
WAIT_QUANTITY = 3
WAIT_UTR = 4
WAIT_REDEEM = 5

# --- CUSTOM EMOJIS (Bot API 9.4+) ---
EMOJI_MAP = {
    "TELEGRAM": "5330237710655306682",
    "PRIME VIDEO": "5346056560537779652",
    "CAPCUT": "5364339557712020484",
    "CHATGPT": "5359726582447487916",
    "EARTH": "6093615976551551886",
    "NETFLIX": "4958664490557112996",
    "SPOTIFY": "4958941520242672323",
    "CRUNCHYROLL": "4958621463574741708",
    "YOUTUBE": "4985489542027936396",
    "EXPRESS VPN": "5796153709931009517",
    "GOOGLE": "5794295402136081349",
    "DUOLINGO": "5796371348808799072",
    "HUB": "6298428643181856596",
    "CANVA": "5796214303329620386",
    "NORD": "5397782960512444700",
    "GROK": "5918183506155933842",
    "CLAUDE": "6124926696161286141",
    "GEMINI": "5319114097545987364",
    "SURFSHARK": "5796592771552777710",
    "P@N*EL": "5217549292205528507",
    "SM PNL": "5217549292205528507",
    "F@PHOUSE": "5373159350363764070",
    "FP HOUSE": "5373159350363764070"
}

def get_prod_emoji_id(name):
    name_upper = name.upper()
    for key, val in EMOJI_MAP.items():
        if key in name_upper: return val
    return None

def get_prod_emoji_tag(name):
    e_id = get_prod_emoji_id(name)
    if e_id: return f'<tg-emoji emoji-id="{e_id}">✨</tg-emoji>'
    return "📦"

def get_prod_symbol(name):
    # This will be used only if icon_custom_emoji_id is not supported
    e_id = get_prod_emoji_id(name)
    alts = {"TELEGRAM": "🔹", "PRIME VIDEO": "🎥", "CAPCUT": "🎬", "CHATGPT": "🤖", "EARTH": "🌍", "NETFLIX": "🍿", "SPOTIFY": "🎧", "CRUNCHYROLL": "🏮", "YOUTUBE": "📺", "CANVA": "🎨", "NORD": "🛡️", "GROK": "🤖", "CLAUDE": "🧠", "GEMINI": "♊", "SURFSHARK": "🦈"}
    for k, v in alts.items():
        if k in name.upper(): return v
    return "📦"

# ==========================================
# 1. DATABASE & HELPERS
# ==========================================
# Redundant init_db removed, using import from db

def get_user(user_id):
    return db_query("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch="one")

def create_or_update_user(user_id, username, language=None):
    u = get_user(user_id)
    if not u:
        db_query("INSERT INTO users (user_id, username, language) VALUES (?, ?, ?)", (user_id, username, language), commit=True)
    else:
        if username: db_query("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id), commit=True)
        if language: db_query("UPDATE users SET language = ? WHERE user_id = ?", (language, user_id), commit=True)

async def is_maintenance():
    res = db_query("SELECT value FROM settings WHERE key='maintenance'", fetch="one")
    return res[0] == 'on' if res else False

async def maintenance_check(update: Update):
    if await is_maintenance():
        msg = "🛠️ <b>System Maintenance</b>\n\nWe are currently optimizing the bot. Please check back later! 🚀"
        if update.callback_query: await update.callback_query.answer("🛠️ Maintenance Active", show_alert=True)
        else: await update.effective_message.reply_text(msg, parse_mode="HTML")
        return True
    return False

# ==========================================
# 2. KEYBOARDS & UI
# ==========================================
def main_reply_keyboard():
    return ReplyKeyboardMarkup([
        ["🛍️ Products", "📥 Deposit"],
        ["👤 My Profile", "📄 Order History"],
        ["👛 My Wallet", "🌐 Language"],
        ["💬 Support", "🎁 Redeem Code"]
    ], resize_keyboard=True)

def dashboard_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Products||emoji:5377660214096974712", callback_data="show_products"),
            InlineKeyboardButton("Redeem Code||emoji:5357292731855033004", callback_data="redeem_start")
        ],
        [
            InlineKeyboardButton("My Profile||emoji:5258011929993026890", callback_data="profile"),
            InlineKeyboardButton("Purchase History||emoji:5355303470507251772", callback_data="history")
        ],
        [
            InlineKeyboardButton("Wallet||emoji:5215420556089776398", callback_data="wallet")
        ],
        [
            InlineKeyboardButton("Support||emoji:5001636926843782163", url="https://t.me/TURNVEB_PREMIUM_SUPPORT"),
            InlineKeyboardButton(" Language||emoji:6093615976551551886", callback_data="change_lang")
        ]
    ])

# ==========================================
# 3. HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    u_id = update.effective_user.id; u_name = update.effective_user.first_name
    create_or_update_user(u_id, u_name)
    
    text = (
        f"<tg-emoji emoji-id=\"5319213852456402176\">💙</tg-emoji> <b>NEXUS MAX DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id=\"5364040533498932357\">💎</tg-emoji> <b>Welcome back, {u_name}!</b>\n\n"
        f"<tg-emoji emoji-id=\"5199785165735367039\">⚡</tg-emoji> <i>Instant delivery is active.</i>\n"
        f"<tg-emoji emoji-id=\"5260463209562776385\">✅</tg-emoji> <i>Verified storefront.</i>\n\n"
        f"<b>Please select a service:</b>"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=dashboard_markup(), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=dashboard_markup(), parse_mode="HTML")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data
    if await maintenance_check(update): return
    if data == "show_products": await show_products(update, context)
    elif data == "profile": await balance_handler(update, context)
    elif data == "history": await purchase_history_handler(update, context)
    elif data == "wallet": await deposit_start(update, context)
    elif data == "change_lang":
        await query.edit_message_text("🌐 <b>Select Language:</b>", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="lang_vi")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ]), parse_mode="HTML")
    elif data.startswith("lang_"):
        lang = data.split('_')[1]
        create_or_update_user(update.effective_user.id, update.effective_user.username, language=lang)
        await query.answer("Language updated! ✨")
        await start(update, context)
    elif data == "redeem_start":
        await query.edit_message_text("🎁 <b>REDEEM GIFT CODE</b>\n\nPlease enter your 12-digit code below:", parse_mode="HTML")
        return WAIT_REDEEM
    elif data == "cancel_purchase": await query.edit_message_text("❌ Purchase cancelled.")
    elif data.startswith("cancel_tx_"): await query.edit_message_text("❌ Transaction cancelled.")
    elif data.startswith("upi_agree_"): await handle_upi_agreement(update, context)

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    query = update.callback_query
    if query: await query.answer()
    products = db_query("SELECT id, name, price_usdt, stock FROM products ORDER BY stock DESC", fetch="all")
    
    if not products:
        msg = "❌ <b>No products found!</b>"
        if query: await query.edit_message_text(msg, parse_mode="HTML")
        else: await update.effective_message.reply_text(msg, parse_mode="HTML")
        return
        
    text = "🛒 <b>Available Products:</b>\n\nChoose a product below:"
    buttons = []
    for p in products:
        e_id = get_prod_emoji_id(p[1])
        symbol = get_prod_symbol(p[1])
        stock_status = " (Out of stock)" if p[3] <= 0 else ""
        btn_text = f"{p[1]} | ${p[2]:.2f}{stock_status}"
        
        if e_id:
            buttons.append([InlineKeyboardButton(f"{btn_text}||emoji:{e_id}", callback_data=f"buy_{p[0]}")])
        else:
            buttons.append([InlineKeyboardButton(f"{symbol} {btn_text}", callback_data=f"buy_{p[0]}")])
            
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    else: await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")

async def handle_buy_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    query = update.callback_query; p_id = int(query.data.split('_')[1])
    product = db_query("SELECT name, price_usdt, stock FROM products WHERE id = ?", (p_id,), fetch="one")
    if not product or product[2] <= 0:
        await query.answer("❌ This item is currently out of stock!", show_alert=True)
        return ConversationHandler.END
    context.user_data.update({"buy_id": p_id, "buy_name": product[0], "buy_price": product[1], "buy_stock": product[2]})
    e_id = get_prod_emoji_id(product[0])
    symbol = get_prod_symbol(product[0])
    icon_html = f"<tg-emoji emoji-id=\"{e_id}\">{symbol}</tg-emoji>" if e_id else symbol
    
    await query.edit_message_text(f"✅ You selected {icon_html} <b>{product[0]}</b> (${product[1]:.2f}).\n\n🖊️ <b>Enter quantity to purchase (max {product[2]}):</b>", parse_mode="HTML")
    return WAIT_QUANTITY

async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Please enter a numeric value.")
        return WAIT_QUANTITY
    qty = int(update.message.text)
    if qty <= 0 or qty > context.user_data["buy_stock"]:
        await update.message.reply_text(f"❌ Invalid quantity. Max available: {context.user_data['buy_stock']}")
        return WAIT_QUANTITY
    context.user_data["buy_qty"] = qty
    total = context.user_data["buy_price"] * qty
    u = get_user(update.effective_user.id); balance = u[4]
    msg = (f"💳 <b>PURCHASE SUMMARY</b>\n━━━━━━━━━━━━━━━━━━━━\n📦 <b>Item:</b> {context.user_data['buy_name']}\n🔢 <b>Qty:</b> {qty}\n💰 <b>Total:</b> <code>{total:.2f} USDT</code>\n━━━━━━━━━━━━━━━━━━━━\nWallet Balance: <code>{balance:.2f} USDT</code>\n\nSelect Payment Method:")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👛 Wallet Balance", callback_data=f"confirm_buy_now_{qty}")],
        [InlineKeyboardButton("🟡 Binance Pay", callback_data=f"manual_pay_binance_{total}")],
        [InlineKeyboardButton("🟢 USDT (BEP20)", callback_data=f"manual_pay_usdt_{total}")],
        [InlineKeyboardButton("🇮🇳 UPI (Instant INR)", callback_data=f"manual_pay_upi_{total}")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_purchase")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")
    return ConversationHandler.END

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = update.effective_user.id
    user_id = update.effective_user.id
    qty, p_id = context.user_data.get("buy_qty"), context.user_data.get("buy_id")
    u = get_user(user_id); balance = u[4]
    p = db_query("SELECT name, price_usdt FROM products WHERE id = ?", (p_id,), fetch="one")
    total = p[1] * qty
    if balance < total:
        await query.answer("❌ Insufficient Wallet Balance!", show_alert=True)
        return
    accounts = db_query("SELECT id, email, password FROM accounts WHERE product_id = ? AND is_sold = 0 LIMIT ?", (p_id, qty), fetch="all")
    if not accounts or len(accounts) < qty:
        db_query("UPDATE products SET stock = (SELECT COUNT(*) FROM accounts WHERE product_id = ? AND is_sold = 0) WHERE id = ?", (p_id, p_id), commit=True)
        await query.answer("❌ Stock mismatch corrected! Please refresh the menu.", show_alert=True)
        return
    try:
        db_query("UPDATE users SET balance_usdt = balance_usdt - ? WHERE user_id = ?", (total, user_id), commit=True)
        acc_text = ""
        for acc in accounts:
            db_query("UPDATE accounts SET is_sold = 1, owner_id = ? WHERE id = ?", (user_id, acc[0]), commit=True)
            acc_text += f"📧 <code>{acc[1]}</code> | 🔑 <code>{acc[2]}</code>\n"
        db_query("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, p_id), commit=True)
        db_query("INSERT INTO orders (user_id, product_id, product_name, qty, total_cost) VALUES (?, ?, ?, ?, ?)", (user_id, p_id, p[0], qty, total), commit=True)
        await query.edit_message_text(f"🎉 <b>SUCCESSFUL PURCHASE!</b>\n━━━━━━━━━━━━━━━━━━━━\n📦 <b>{p[0]}</b>\n💰 <b>Paid:</b> {total:.2f} USDT\n━━━━━━━━━━━━━━━━━━━━\n🎁 <b>ACCOUNTS DELIVERED:</b>\n{acc_text}\n━━━━━━━━━━━━━━━━━━━━\n🛡️ <i>Trusted with Nexus Security</i>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Purchase failed: {e}"); await query.answer("❌ Transaction Error.")

async def handle_manual_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    method = query.data.split('_')[2]; amt = float(query.data.split('_')[3])
    context.user_data.update({"dep_amt": amt, "dep_method": method, "waiting_for_screenshot": True})
    
    if method == "upi":
        text = (
            "⚠️ <b>UPI TERMS & CONDITIONS</b> ⚠️\n━━━━━━━━━━━━━━━━━━━━\n"
            "1. The fixed conversion rate is ₹95 per $1 USD.\n"
            "2. You MUST scan and pay using the generated QR code ONLY.\n"
            "3. Do NOT modify or change the pre-filled amount in your UPI app.\n"
            "4. No refunds will be provided for incorrect payments.\n\n"
            "<b>Do you agree to these terms?</b>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Agree", callback_data=f"upi_agree_{amt}"), InlineKeyboardButton("❌ Cancel", callback_data="cancel_tx")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        return

    code = ''.join(random.choices(string.digits, k=16))
    db_query("INSERT INTO transactions (user_id, amount, unique_code, status) VALUES (?, ?, ?, 'pending')", (update.effective_user.id, amt, code), commit=True)
    tx = db_query("SELECT id FROM transactions WHERE unique_code = ?", (code,), fetch="one")
    context.user_data["pending_tx_id"] = tx[0]
    
    if method == "binance": text = f"🟡 <b>BINANCE PAY</b>\n💰 Pay: <code>{amt:.2f} USDT</code>\n🆔 ID: <code>{BINANCE_ID}</code>\n\n📸 <b>Upload Screenshot!</b>"
    elif method == "usdt": text = f"🟢 <b>USDT (BEP20)</b>\n💰 Pay: <code>{amt:.2f} USDT</code>\n💳 Addr: <code>{USDT_BEP20_ADDRESS}</code>\n\n📸 <b>Upload Screenshot!</b>"
    await query.edit_message_text(text, parse_mode="HTML")

async def handle_upi_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    amt = float(query.data.split('_')[2])
    
    code = ''.join(random.choices(string.digits, k=16))
    db_query("INSERT INTO transactions (user_id, amount, unique_code, status) VALUES (?, ?, ?, 'pending')", (update.effective_user.id, amt, code), commit=True)
    tx = db_query("SELECT id FROM transactions WHERE unique_code = ?", (code,), fetch="one")
    tx_id = tx[0]
    context.user_data["pending_tx_id"] = tx_id
    
    inr = round(amt * 95, 2)
    url = f"upi://pay?pa={UPI_ID}&pn=NexusMax&am={inr}&cu=INR&tn=NEX_{tx_id}"
    qr = qrcode.make(url); buf = io.BytesIO(); qr.save(buf, format="PNG"); buf.seek(0)
    
    caption = (
        "🇮🇳 <b>UPI PAYMENT</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Amount:</b> ₹{inr:.2f}\n"
        f"📋 <b>Order ID:</b> <code>NEX_{tx_id}</code>\n\n"
        "<b>Instructions:</b>\n"
        "1. Scan QR with Paytm, PhonePe, or GPay.\n"
        "2. Complete payment of exactly ₹{inr:.2f}.\n"
        "3. <b>Send a SCREENSHOT of successful payment here!</b> 📸\n\n"
        "<i>Admin will verify and add balance instantly.</i>"
    )
    await query.message.reply_photo(photo=buf, caption=caption, parse_mode="HTML")
    await query.message.delete()

async def deposit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    await update.effective_message.reply_text("📥 <b>WALLET DEPOSIT</b>\n━━━━━━━━━━━━━━━━━━━━\n<b>Enter Amount (USDT):</b>\n<i>Min: 5 USDT</i>", parse_mode="HTML")
    return WAIT_AMOUNT

async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: amt = float(update.message.text)
    except: await update.message.reply_text("❌ Invalid amount."); return WAIT_AMOUNT
    if amt < 5: await update.message.reply_text("❌ Min 5 USDT."); return WAIT_AMOUNT
    context.user_data["dep_amt"] = amt
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Binance Pay||emoji:5454205576512818013", callback_data=f"manual_pay_binance_{amt}"), 
            InlineKeyboardButton("USDT (BEP20)||emoji:5195308461193182892", callback_data=f"manual_pay_usdt_{amt}")
        ],
        [InlineKeyboardButton("UPI (₹95 Rate)||emoji:6082662276643425446", callback_data=f"manual_pay_upi_{amt}")],
        [InlineKeyboardButton("Cancel", callback_data="cancel_tx")]
    ])
    await update.message.reply_text(f"💰 <b>Amount:</b> <code>{amt:.2f} USDT</code>\nSelect Payment Gateway:", reply_markup=kb, parse_mode="HTML")
    return ConversationHandler.END

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_for_screenshot"): return
    tx_id, amt = context.user_data["pending_tx_id"], context.user_data["dep_amt"]; user = update.effective_user
    method = context.user_data.get("dep_method", "unknown").upper()
    notif = f"🚨 <b>PAYMENT REVIEW</b>\n👤 {user.first_name} (@{user.username})\n🆔 <code>{user.id}</code>\n💰 <code>{amt} USDT</code>\n💳 <b>Method:</b> {method}\n📦 <code>NEX_{tx_id}</code>"
    kb = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"pay_appr_{tx_id}"},
            {"text": "❌ Reject", "callback_data": f"pay_rej_{tx_id}"}
        ]]
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage", json={
                "chat_id": ADMIN_ID, 
                "text": notif, 
                "parse_mode": "HTML",
                "reply_markup": kb
            })
            await client.post(f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendPhoto", json={
                "chat_id": ADMIN_ID, 
                "photo": update.message.photo[-1].file_id
            })
        except Exception as e:
            logger.error(f"Failed to send admin notification: {e}")
    await update.message.reply_text("✅ <b>Screenshot Received!</b>\nAdmin is reviewing. Type your UTR/Ref below:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Submit Ref", callback_data=f"upi_paid_{tx_id}")]]), parse_mode="HTML")
    context.user_data["waiting_for_screenshot"] = False

async def verify_tx_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data["pending_tx_id"] = int(query.data.split('_')[2])
    await query.edit_message_text("🔢 <b>Enter your 12-digit UTR/Ref number:</b>", parse_mode="HTML")
    return WAIT_UTR

async def handle_utr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utr = update.message.text.strip(); tx_id = context.user_data.get("pending_tx_id")
    db_query("UPDATE transactions SET utr = ?, status = 'review' WHERE id = ?", (utr, tx_id), commit=True)
    async with httpx.AsyncClient() as client:
        try: await client.post(f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage", json={"chat_id": ADMIN_ID, "text": f"📝 <b>UTR SUBMITTED</b>\nTX: NEX_{tx_id}\nUTR: <code>{utr}</code>", "parse_mode": "HTML"})
        except: pass
    await update.message.reply_text("✅ <b>Ref Submitted!</b> Admin will verify shortly.", parse_mode="HTML")
    return ConversationHandler.END

async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    u = get_user(update.effective_user.id)
    text = (
        f"<tg-emoji emoji-id=\"5431684550424011313\">🏷️</tg-emoji> <b>USER ACCOUNT PROFILE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>User ID:</b> <code>{u[0]}</code>\n"
        f"💰 <b>Balance:</b> <code>${u[4]:.2f} USDT</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id=\"5345905193005371012\">🌀</tg-emoji> <b>Status:</b> Premium Member\n"
        f"<tg-emoji emoji-id=\"5260463209562776385\">✅</tg-emoji> <b>Verified Access</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <i>Nexus Security Protocol Active</i>"
    )
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=dashboard_markup(), parse_mode="HTML")
    else: await update.effective_message.reply_text(text, reply_markup=dashboard_markup(), parse_mode="HTML")

async def purchase_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    rows = db_query("SELECT product_name, qty, total_cost, timestamp FROM orders WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (update.effective_user.id,), fetch="all")
    if not rows:
        if update.callback_query: await update.callback_query.answer("No orders found.", show_alert=True)
        else: await update.message.reply_text("❌ No purchase history found.")
        return
    text = "<tg-emoji emoji-id=\"5355303470507251772\">📄</tg-emoji> <b>PURCHASE HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for r in rows: text += f"<tg-emoji emoji-id=\"5260463209562776385\">✅</tg-emoji> <b>{r[0]}</b>\nQty: {r[1]} | ${r[2]:.2f}\n📅 {r[3][:16]}\n\n"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="profile")]]), parse_mode="HTML")
    else: await update.message.reply_text(text, parse_mode="HTML")

async def handle_redeem_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await maintenance_check(update): return
    msg = "🎁 <b>REDEEM GIFT CODE</b>\n\nPlease enter your 12-digit code below:"
    if update.callback_query: await update.callback_query.edit_message_text(msg, parse_mode="HTML")
    else: await update.message.reply_text(msg, parse_mode="HTML")
    return WAIT_REDEEM

async def handle_redeem_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    res = db_query("SELECT value FROM redeem_codes WHERE code = ? AND is_used = 0", (code,), fetch="one")
    if res:
        val = res[0]
        db_query("UPDATE redeem_codes SET is_used = 1, used_by = ? WHERE code = ?", (update.effective_user.id, code), commit=True)
        db_query("UPDATE users SET balance_usdt = balance_usdt + ? WHERE user_id = ?", (val, update.effective_user.id), commit=True)
        await update.message.reply_text(f"🎁 <b>Success!</b> Code redeemed for <code>{val:.2f} USDT</code>.", parse_mode="HTML")
    else: await update.message.reply_text("❌ <b>Invalid code.</b>", parse_mode="HTML")
    return ConversationHandler.END

def main():
    init_db(); app = ApplicationBuilder().token(TOKEN).job_queue(None).build()
    buy_conv = ConversationHandler(entry_points=[CallbackQueryHandler(handle_buy_click, pattern="^buy_")], states={WAIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity)]}, fallbacks=[CommandHandler("start", start)])
    dep_conv = ConversationHandler(entry_points=[MessageHandler(filters.Regex("^📥 Deposit$"), deposit_start), CallbackQueryHandler(deposit_start, pattern="^wallet$")], states={WAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deposit_amount)], WAIT_UTR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_utr)]}, fallbacks=[CommandHandler("start", start)])
    red_conv = ConversationHandler(entry_points=[MessageHandler(filters.Regex("^🎁 Redeem Code$"), handle_redeem_entry), CallbackQueryHandler(handle_redeem_entry, pattern="^redeem_start$")], states={WAIT_REDEEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_redeem_finish)]}, fallbacks=[CommandHandler("start", start)])
    app.add_handler(CommandHandler("start", start)); app.add_handler(buy_conv); app.add_handler(dep_conv); app.add_handler(red_conv)
    app.add_handler(CallbackQueryHandler(handle_manual_pay, pattern="^manual_pay_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase, pattern="^confirm_buy_now_"))
    app.add_handler(CallbackQueryHandler(show_products, pattern="^show_products$"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ Products$"), show_products))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), balance_handler))
    app.add_handler(MessageHandler(filters.Regex("^📄 Order History$"), purchase_history_handler))
    print("Nexus Max Premium Bot is LIVE!"); app.run_polling()

if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); main()
    except KeyboardInterrupt: pass
