import logging
import os
import random
import string
import httpx
import html
import io
import qrcode
import asyncio
import sys
import sqlite3
from datetime import datetime

# Railway / Environment Variables
TOKEN = os.getenv("BOT_TOKEN", "8203606211:AAGNWwowtjnPMoI5uxo6Pt5j7a_5-srfCAo")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7529580444"))
DB_NAME = os.getenv("DB_NAME", "nexus_bot.db")
DATABASE_URL = os.getenv("DATABASE_URL")
BINANCE_ID = os.getenv("BINANCE_ID", "1129378736")
USDT_BEP20_ADDRESS = os.getenv("USDT_BEP20_ADDRESS", "0xfaa43c4c6e783b740470306fd18e4db3ab7824ad")
UPI_ID = os.getenv("UPI_ID", "begumop@fam")
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "8725003968:AAHnPLZWjoCsIPt4hKYEmzQmLkkRBogVBnQ")

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

# Monkey patch
original_to_dict = InlineKeyboardButton.to_dict
def custom_to_dict(self, *args, **kwargs):
    d = original_to_dict(self, *args, **kwargs)
    if 'text' in d and '||emoji:' in d['text']:
        parts = d['text'].split('||emoji:')
        d['text'] = parts[0]
        d['icon_custom_emoji_id'] = parts[1]
    return d
InlineKeyboardButton.to_dict = custom_to_dict

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

def get_db_conn():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_NAME)

def db_query(query, params=(), fetch="none", commit=False):
    conn = get_db_conn()
    if DATABASE_URL: query = query.replace('?', '%s')
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        res = None
        if fetch == "one": res = cur.fetchone()
        elif fetch == "all": res = cur.fetchall()
        if commit: conn.commit()
        return res
    finally: conn.close()

def init_db():
    conn = get_db_conn(); cur = conn.cursor()
    schema = '''
        CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, language TEXT, balance_usdt REAL DEFAULT 0.00);
        CREATE TABLE IF NOT EXISTS products (id SERIAL PRIMARY KEY, name TEXT, price_usdt REAL, stock INTEGER);
        CREATE TABLE IF NOT EXISTS transactions (id SERIAL PRIMARY KEY, user_id BIGINT, amount REAL, unique_code TEXT, status TEXT, utr TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, product_id INTEGER, email TEXT, password TEXT, is_sold INTEGER DEFAULT 0, owner_id BIGINT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, user_id BIGINT, product_id INTEGER, product_name TEXT, qty INTEGER, total_cost REAL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS redeem_codes (code TEXT PRIMARY KEY, value REAL, is_used INTEGER DEFAULT 0, used_by BIGINT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    '''
    if not DATABASE_URL:
        schema = schema.replace('BIGINT', 'INTEGER').replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT').replace('TIMESTAMP', 'DATETIME')
    for cmd in schema.split(';'):
        if cmd.strip(): cur.execute(cmd)
    cur.execute("INSERT INTO settings (key, value) VALUES ('maintenance', 'off') ON CONFLICT (key) DO NOTHING")
    conn.commit(); conn.close()

WAIT_AMOUNT, WAIT_TXID, WAIT_QUANTITY, WAIT_UTR, WAIT_REDEEM = range(1, 6)
EMOJI_MAP = {"TELEGRAM": "5330237710655306682", "CHATGPT": "5359726582447487916", "NETFLIX": "4958664490557112996", "SPOTIFY": "4958941520242672323", "YOUTUBE": "4985489542027936396"}

def get_prod_emoji_id(name):
    for k, v in EMOJI_MAP.items():
        if k in name.upper(): return v
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = update.effective_user.id; u_name = update.effective_user.first_name
    db_query("INSERT INTO users (user_id, username, balance_usdt) VALUES (?, ?, 0) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (u_id, u_name), commit=True)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Products", callback_data="show_products")], [InlineKeyboardButton("Profile", callback_data="profile"), InlineKeyboardButton("Wallet", callback_data="wallet")]])
    await update.message.reply_text(f"Welcome {u_name}!", reply_markup=kb)

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = db_query("SELECT id, name, price_usdt, stock FROM products WHERE stock > 0", fetch="all")
    if not products: await update.effective_message.reply_text("Sold out!"); return
    btns = [[InlineKeyboardButton(f"{p[1]} | ${p[2]}", callback_data=f"buy_{p[0]}")] for p in products]
    await update.effective_message.reply_text("Products:", reply_markup=InlineKeyboardMarkup(btns))

async def handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p_id = int(update.callback_query.data.split('_')[1])
    p = db_query("SELECT name, price_usdt, stock FROM products WHERE id = ?", (p_id,), fetch="one")
    context.user_data.update({"buy_id": p_id, "buy_name": p[0], "buy_price": p[1], "buy_stock": p[2]})
    await update.callback_query.edit_message_text(f"Buying {p[0]}. Quantity?")
    return WAIT_QUANTITY

async def handle_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = int(update.message.text); total = qty * context.user_data["buy_price"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Pay with Wallet", callback_data=f"confirm_buy_{qty}")]])
    await update.message.reply_text(f"Total: ${total}. Confirm?", reply_markup=kb)
    return ConversationHandler.END

async def confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; qty = int(update.callback_query.data.split('_')[2]); p_id = context.user_data["buy_id"]
    p = db_query("SELECT name, price_usdt FROM products WHERE id = ?", (p_id,), fetch="one")
    total = p[1] * qty
    u = db_query("SELECT balance_usdt FROM users WHERE user_id = ?", (user_id,), fetch="one")
    if u[0] < total: await update.callback_query.answer("No balance!"); return
    accs = db_query("SELECT id, email, password FROM accounts WHERE product_id = ? AND is_sold = 0 LIMIT ?", (p_id, qty), fetch="all")
    db_query("UPDATE users SET balance_usdt = balance_usdt - ? WHERE user_id = ?", (total, user_id), commit=True)
    res_text = ""
    for a in accs:
        db_query("UPDATE accounts SET is_sold = 1, owner_id = ? WHERE id = ?", (user_id, a[0]), commit=True)
        res_text += f"{a[1]}:{a[2]}\n"
    db_query("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, p_id), commit=True)
    await update.callback_query.edit_message_text(f"Success!\n{res_text}")

def main():
    init_db(); app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_products, pattern="^show_products$"))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(handle_buy, pattern="^buy_")], states={WAIT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_qty)]}, fallbacks=[]))
    app.add_handler(CallbackQueryHandler(confirm_buy, pattern="^confirm_buy_"))
    print("Bot starting..."); app.run_polling()

if __name__ == "__main__": main()
