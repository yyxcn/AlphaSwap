.PHONY: build test deploy agent abi clean

# ── Contracts ────────────────────────────────────────────
build:
	cd contracts && forge build

test:
	cd contracts && forge test -v

deploy:
	cd contracts && forge script script/Deploy.s.sol \
		--rpc-url $(BSC_TESTNET_RPC) \
		--broadcast \
		--verify

# ── Python Agent ─────────────────────────────────────────
venv:
	python3.13 -m venv .venv
	.venv/bin/pip install -r agent/requirements.txt

agent:
	cd agent && ../.venv/bin/python main.py

# ── ABI Export ───────────────────────────────────────────
abi: build
	@mkdir -p abi
	@for c in Vault TradeRegistry MockRouter MockERC20; do \
		python3.13 -c "import json; d=json.load(open('contracts/out/$$c.sol/$$c.json')); json.dump(d['abi'],open('abi/$$c.json','w'),indent=2)"; \
		echo "Exported abi/$$c.json"; \
	done

# ── Clean ────────────────────────────────────────────────
clean:
	cd contracts && forge clean
	rm -rf abi/*.json
