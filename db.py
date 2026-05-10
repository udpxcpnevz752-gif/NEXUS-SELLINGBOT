import os
import sqlite3
import logging

logger = logging.getLogger(__name__)
DB_NAME = "nexus_bot.db"
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_conn():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_NAME)

def db_query(query, params=(), fetch="none", commit=False):
    conn = get_db_conn()
    # Support both ? and %s for different DB engines
    if DATABASE_URL:
        query = query.replace('?', '%s')
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        res = None
        if fetch == "one":
            res = cur.fetchone()
        elif fetch == "all":
            res = cur.fetchall()
        
        if commit:
            conn.commit()
        return res
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return None
    finally:
        conn.close()

def init_db():
    conn = get_db_conn(); c = conn.cursor()
    schema = '''
        CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, language TEXT, balance_vnd REAL DEFAULT 0, balance_usdt REAL DEFAULT 0.00, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS products (id SERIAL PRIMARY KEY, name TEXT, price_usdt REAL, stock INTEGER);
        CREATE TABLE IF NOT EXISTS transactions (id SERIAL PRIMARY KEY, user_id BIGINT, amount REAL, unique_code TEXT, status TEXT, tx_hash TEXT, utr TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS accounts (id SERIAL PRIMARY KEY, product_id INTEGER, email TEXT, password TEXT, is_sold INTEGER DEFAULT 0, owner_id BIGINT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, user_id BIGINT, product_id INTEGER, product_name TEXT, qty INTEGER, total_cost REAL, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS redeem_codes (code TEXT PRIMARY KEY, value REAL, is_used INTEGER DEFAULT 0, used_by BIGINT DEFAULT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    '''
    if not DATABASE_URL:
        schema = schema.replace('BIGINT', 'INTEGER').replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT').replace('TIMESTAMP', 'DATETIME')
    
    for cmd in schema.split(';'):
        if cmd.strip():
            c.execute(cmd)
            
    c.execute("INSERT INTO settings (key, value) VALUES ('maintenance', 'off') ON CONFLICT (key) DO NOTHING")
    conn.commit(); conn.close()
