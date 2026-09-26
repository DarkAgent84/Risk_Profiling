"""
PostgreSQL / pgAdmin Database Configuration
"""
from src.db import DB_CONFIG, get_engine, get_raw_connection, ensure_database_exists

# Database connection dictionary
DATABASE_NAME = DB_CONFIG["dbname"]
DATABASE_USER = DB_CONFIG["user"]
DATABASE_PASSWORD = DB_CONFIG["password"]
DATABASE_HOST = DB_CONFIG["host"]
DATABASE_PORT = DB_CONFIG["port"]
