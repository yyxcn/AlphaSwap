import json
from pathlib import Path
from web3 import Web3
from config import (
    BSC_TESTNET_RPC,
    AGENT_PRIVATE_KEY,
    VAULT_ADDRESS,
    TRADE_REGISTRY_ADDRESS,
    BSC_TESTNET_CHAIN_ID,
)

w3 = Web3(Web3.HTTPProvider(BSC_TESTNET_RPC))

# Load ABIs from Foundry artifacts
CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts" / "out"


def _load_abi(contract_name: str) -> list:
    artifact = CONTRACTS_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    with open(artifact) as f:
        return json.load(f)["abi"]


def _get_vault():
    abi = _load_abi("Vault")
    return w3.eth.contract(address=Web3.to_checksum_address(VAULT_ADDRESS), abi=abi)


def _get_registry():
    abi = _load_abi("TradeRegistry")
    return w3.eth.contract(address=Web3.to_checksum_address(TRADE_REGISTRY_ADDRESS), abi=abi)


def _get_account():
    return w3.eth.account.from_key(AGENT_PRIVATE_KEY)


def _send_tx(func):
    """Build, sign, and send a contract function call."""
    account = _get_account()
    tx = func.build_transaction({
        "chainId": BSC_TESTNET_CHAIN_ID,
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 500_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    return receipt


def execute_buy(user: str, amount_in: int) -> dict:
    """Execute a buy via Vault.executeBuy()."""
    vault = _get_vault()
    receipt = _send_tx(vault.functions.executeBuy(
        Web3.to_checksum_address(user),
        amount_in,
    ))
    return {
        "tx_hash": receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "failed",
        "gas_used": receipt.gasUsed,
    }


def execute_sell(user: str, amount_in: int) -> dict:
    """Execute a sell via Vault.executeSell()."""
    vault = _get_vault()
    receipt = _send_tx(vault.functions.executeSell(
        Web3.to_checksum_address(user),
        amount_in,
    ))
    return {
        "tx_hash": receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "failed",
        "gas_used": receipt.gasUsed,
    }


def record_trade(
    user: str,
    pair: str,
    is_buy: bool,
    amount_in: int,
    amount_out: int,
    price: int,
    ai_reasoning: str,
    confidence: int,
) -> dict:
    """Record a trade in TradeRegistry."""
    registry = _get_registry()
    receipt = _send_tx(registry.functions.recordTrade(
        Web3.to_checksum_address(user),
        pair,
        is_buy,
        amount_in,
        amount_out,
        price,
        ai_reasoning,
        confidence,
    ))
    return {
        "tx_hash": receipt.transactionHash.hex(),
        "status": "success" if receipt.status == 1 else "failed",
        "gas_used": receipt.gasUsed,
    }


def get_user_balances(user: str) -> dict:
    """Read user balances from Vault."""
    vault = _get_vault()
    quote, base = vault.functions.getUserBalances(Web3.to_checksum_address(user)).call()
    return {"usdt": quote, "bnb": base}


def get_recent_trades(count: int = 20) -> list:
    """Read recent trades from TradeRegistry."""
    registry = _get_registry()
    trades = registry.functions.getRecentTrades(count).call()
    return [
        {
            "user": t[0],
            "pair": t[1],
            "is_buy": t[2],
            "amount_in": t[3],
            "amount_out": t[4],
            "price": t[5],
            "ai_reasoning": t[6],
            "confidence": t[7],
            "timestamp": t[8],
        }
        for t in trades
    ]
