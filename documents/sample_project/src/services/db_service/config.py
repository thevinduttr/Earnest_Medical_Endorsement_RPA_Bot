from dotenv import load_dotenv
import os

load_dotenv()

class DBConfig:
    # Azure SQL Database credentials from environment variables
    SERVER = os.getenv('DB_SERVER')
    DATABASE = os.getenv('DB_DATABASE')
    USERNAME = os.getenv('DB_USERNAME')
    PASSWORD = os.getenv('DB_PASSWORD')
    DRIVER = os.getenv('DB_DRIVER')
