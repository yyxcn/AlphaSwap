import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# RPC
BSC_TESTNET_RPC = os.getenv("BSC_TESTNET_RPC", "https://data-seed-prebsc-1-s1.binance.org:8545/")
BSC_MAINNET_RPC = os.getenv("BSC_MAINNET_RPC", "https://bsc-dataseed.binance.org/")

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
COINGECKO_API_URL = os.getenv("COINGECKO_API_URL", "https://api.coingecko.com/api/v3")

# Agent wallet
AGENT_PRIVATE_KEY = os.getenv("AGENT_PRIVATE_KEY", "")

# PancakeSwap V3 BNB/USDT pool (BSC mainnet, read-only)
PANCAKE_BNB_USDT_POOL = os.getenv("PANCAKE_BNB_USDT_POOL", "0x36696169C63e42cd08ce11f5deeBbCeBae652050")

# Contract addresses (fill after deployment)
VAULT_ADDRESS = os.getenv("VAULT_ADDRESS", "")
TRADE_REGISTRY_ADDRESS = os.getenv("TRADE_REGISTRY_ADDRESS", "")
MOCK_ROUTER_ADDRESS = os.getenv("MOCK_ROUTER_ADDRESS", "")
MOCK_USDT_ADDRESS = os.getenv("MOCK_USDT_ADDRESS", "")
MOCK_BNB_ADDRESS = os.getenv("MOCK_BNB_ADDRESS", "")

# Monitoring
MONITOR_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))

# Chain
BSC_TESTNET_CHAIN_ID = 97
