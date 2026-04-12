// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/MockERC20.sol";
import "../src/MockRouter.sol";
import "../src/Vault.sol";
import "../src/TradeRegistry.sol";

contract Deploy is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("AGENT_PRIVATE_KEY");
        address agent = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);

        // 1. Deploy mock tokens
        MockERC20 mockUSDT = new MockERC20("Mock USDT", "USDT", 18);
        MockERC20 mockBNB = new MockERC20("Mock BNB", "WBNB", 18);

        // 2. Deploy router & set rate (1 BNB = 600 USDT)
        MockRouter router = new MockRouter();
        router.setRate(address(mockBNB), address(mockUSDT), 600e18);

        // 3. Deploy vault
        Vault vault = new Vault(address(mockUSDT), address(mockBNB), address(router));
        vault.setAuthorized(agent, true);

        // 4. Deploy trade registry
        TradeRegistry registry = new TradeRegistry();
        registry.setAuthorized(agent, true);

        // 5. Mint liquidity for router
        mockUSDT.mint(address(router), 10_000_000e18);  // 10M USDT
        mockBNB.mint(address(router), 50_000e18);        // 50K BNB

        // 6. Mint test tokens for deployer
        mockUSDT.mint(agent, 100_000e18);  // 100K USDT for testing

        vm.stopBroadcast();

        // Log deployed addresses
        console.log("========== DEPLOYED ADDRESSES ==========");
        console.log("MockUSDT:      ", address(mockUSDT));
        console.log("MockBNB:       ", address(mockBNB));
        console.log("MockRouter:    ", address(router));
        console.log("Vault:         ", address(vault));
        console.log("TradeRegistry: ", address(registry));
        console.log("Agent:         ", agent);
        console.log("=========================================");
    }
}
