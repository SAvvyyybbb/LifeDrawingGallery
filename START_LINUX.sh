#!/bin/bash

# LifeDrawingGallery - Linux Launcher

echo "========================================"
echo "  LifeDrawingGallery - Linux Launcher"
echo "========================================"

# Ensure script runs from project root
cd "$(dirname "$0")"

# 1. Dependency Checks
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 is not installed. Please install it first."
    exit 1
fi

if ! command -v git &> /dev/null; then
    echo "[ERROR] Git is not installed."
    echo "Please download it from: https://git-scm.com/downloads"
    exit 1
fi

# 2. Configuration Wizard
if [ ! -f ".env" ]; then
    echo "[INFO] No .env file found. Starting first-run setup..."
    
    if [ ! -f "example.env" ]; then
        # Create a basic example.env if it doesn't exist
        echo "DISCORD_TOKEN=your_token_here" > example.env
        echo "SUPABASE_URL=your_supabase_url" >> example.env
        echo "SUPABASE_ANON_KEY=your_supabase_key" >> example.env
        echo "DB_URL=postgresql://..." >> example.env
    fi
    
    cp example.env .env
    echo "[ACTION] Opening .env for editing. Please enter your credentials and SAVE the file."
    
    # Try to open in default editor
    if command -v xdg-open &> /dev/null; then
        xdg-open .env
    elif command -v nano &> /dev/null; then
        nano .env
    else
        echo "[WARNING] Could not open editor automatically. Please open .env manually."
    fi
    
    echo "========================================"
    echo "  SETUP PAUSED"
    echo "  Please edit .env, save it, and then RE-RUN this script."
    echo "========================================"
    exit 0
fi

# 3. Virtual Environment
if [ ! -f "venv/bin/activate" ]; then
    echo "[1/3] Creating/Repairing Virtual Environment..."
    # Remove broken venv if it exists
    rm -rf venv
    python3 -m venv venv
    if [ ! -f "venv/bin/activate" ]; then
        echo "[ERROR] Failed to create virtual environment."
        echo "Please try: sudo apt install python3-venv"
        exit 1
    fi
fi

# 4. Dependencies
echo "[2/3] Checking Dependencies..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to activate virtual environment."
    exit 1
fi

# Ensure we are using the venv's pip
python3 -m pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies."
    exit 1
fi

# 5. Launch Processes
echo "[3/3] Starting Services..."
echo ""

# Kill existing processes on target port
fuser -k 8501/tcp > /dev/null 2>&1

# Start Streamlit in background
streamlit run Home.py --server.port 8501 --server.headless true &
echo ""
echo "🚀 DASHBOARD IS READY!"
echo "👉 Click here: http://localhost:8501"
echo ""

# Start Scraper in background
python3 discord_scraper.py &
echo "[Scraper] Starting Discord Bot in background..."

echo ""
echo "========================================"
echo "  ALL SERVICES STARTED SUCCESSFULLY"
echo "  Keep this window open. Press Ctrl+C to stop."
echo "========================================"

# Keep script alive and handle shutdown
trap "kill 0" EXIT
wait
