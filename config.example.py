# ============================================================
# SBA Business Search — Configuration Template
# ============================================================
# 1. Copy this file to config.py
# 2. Fill in your MySQL password and CSV file paths
# 3. Never commit config.py to git (it's in .gitignore)

MYSQL_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "YOUR_MYSQL_PASSWORD_HERE",
    "database": "sba_leads",
    "charset":  "utf8mb4",
}

# Absolute paths to your SBA PPP CSV files
# Download from: https://data.sba.gov/dataset/ppp-foia
CSV_FILES = [
    r"C:\path\to\public_150k_plus_240930.csv",
    r"C:\path\to\public_up_to_150k_2_240930.csv",
]

# CSV encoding (SBA files use latin-1)
CSV_ENCODING = "latin-1"

# Flask server settings
FLASK_HOST  = "127.0.0.1"
FLASK_PORT  = 5000
FLASK_DEBUG = True
