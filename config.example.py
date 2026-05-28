# ============================================================
# SBA Business Search — Configuration Template
# ============================================================
# 1. Copy this file to config.py
# 2. Fill in your PostgreSQL password and CSV file paths
# 3. Never commit config.py to git (it's in .gitignore)

PG_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "user":     "postgres",
    "password": "YOUR_PG_PASSWORD_HERE",
    "dbname":   "sba_leads",
}

# Absolute paths to your SBA PPP CSV files
# Download from: https://data.sba.gov/dataset/ppp-foia
CSV_FILES = [
    r"C:\path\to\public_150k_plus_240930.csv",
    r"C:\path\to\public_up_to_150k_2_240930.csv",
]

# CSV encoding (SBA files use latin-1)
CSV_ENCODING = "latin-1"

# Google Places API key — NEVER commit this file to git (.gitignore covers it)
GOOGLE_PLACES_API_KEY = "YOUR_GOOGLE_PLACES_API_KEY_HERE"

# Flask server settings
FLASK_HOST  = "127.0.0.1"
FLASK_PORT  = 5000
FLASK_DEBUG = True
