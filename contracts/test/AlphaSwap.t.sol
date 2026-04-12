// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/MockERC20.sol";
import "../src/MockRouter.sol";
import "../src/Vault.sol";
import "../src/TradeRegistry.sol";

contract AlphaSwapTest is Test {
    MockERC20 usdt;
    MockERC20 bnb;
    MockRouter router;
    Vault vault;
    TradeRegistry registry;

    address owner = address(this);
    address agent = address(0xA1);
    address user1 = address(0xB1);

    function setUp() public {
        // Deploy tokens
        usdt = new MockERC20("Mock USDT", "USDT", 18);
        bnb = new MockERC20("Mock BNB", "WBNB", 18);

        // Deploy router & set rate: 1 BNB = 600 USDT
        router = new MockRouter();
        router.setRate(address(bnb), address(usdt), 600e18);

        // Fund router with liquidity
        usdt.mint(address(router), 1_000_000e18);
        bnb.mint(address(router), 10_000e18);

        // Deploy vault
        vault = new Vault(address(usdt), address(bnb), address(router));
        vault.setAuthorized(agent, true);

        // Deploy registry
        registry = new TradeRegistry();
        registry.setAuthorized(agent, true);

        // Give user1 some USDT
        usdt.mint(user1, 10_000e18);
    }

    // ========== MockERC20 Tests ==========

    function test_MockERC20_Mint() public {
        usdt.mint(address(0xC1), 1000e18);
        assertEq(usdt.balanceOf(address(0xC1)), 1000e18);
    }

    function test_MockERC20_Decimals() public view {
        assertEq(usdt.decimals(), 18);
        assertEq(bnb.decimals(), 18);
    }

    // ========== MockRouter Tests ==========

    function test_Router_SetRate() public view {
        assertEq(router.rates(address(bnb), address(usdt)), 600e18);
        // inverse: 1 USDT = 1/600 BNB
        uint256 inverseRate = router.rates(address(usdt), address(bnb));
        assertGt(inverseRate, 0);
    }

    function test_Router_Swap() public {
        // Swap 1 BNB -> USDT
        bnb.mint(address(this), 1e18);
        bnb.approve(address(router), 1e18);

        address[] memory path = new address[](2);
        path[0] = address(bnb);
        path[1] = address(usdt);

        uint256[] memory amounts = router.swapExactTokensForTokens(
            1e18, 0, path, address(this), block.timestamp + 300
        );

        assertEq(amounts[0], 1e18);
        assertEq(amounts[1], 600e18);
        assertEq(usdt.balanceOf(address(this)), 600e18);
    }

    function test_Router_GetAmountsOut() public view {
        address[] memory path = new address[](2);
        path[0] = address(bnb);
        path[1] = address(usdt);

        uint256[] memory amounts = router.getAmountsOut(1e18, path);
        assertEq(amounts[1], 600e18);
    }

    function test_Router_RevertNoRate() public {
        address fakeToken = address(0xDEAD);

        address[] memory path = new address[](2);
        path[0] = address(bnb);
        path[1] = fakeToken;

        bnb.mint(address(this), 1e18);
        bnb.approve(address(router), 1e18);

        vm.expectRevert("MockRouter: NO_RATE");
        router.swapExactTokensForTokens(1e18, 0, path, address(this), block.timestamp + 300);
    }

    // ========== Vault Tests ==========

    function test_Vault_Deposit() public {
        vm.startPrank(user1);
        usdt.approve(address(vault), 1000e18);
        vault.deposit(1000e18);
        vm.stopPrank();

        (uint256 quote, uint256 base) = vault.getUserBalances(user1);
        assertEq(quote, 1000e18);
        assertEq(base, 0);
    }

    function test_Vault_Withdraw() public {
        vm.startPrank(user1);
        usdt.approve(address(vault), 1000e18);
        vault.deposit(1000e18);
        vault.withdraw(500e18);
        vm.stopPrank();

        (uint256 quote,) = vault.getUserBalances(user1);
        assertEq(quote, 500e18);
        assertEq(usdt.balanceOf(user1), 9500e18);
    }

    function test_Vault_WithdrawRevertInsufficient() public {
        vm.prank(user1);
        vm.expectRevert("Vault: insufficient balance");
        vault.withdraw(100e18);
    }

    function test_Vault_ExecuteBuy() public {
        // User deposits 600 USDT
        vm.startPrank(user1);
        usdt.approve(address(vault), 600e18);
        vault.deposit(600e18);
        vm.stopPrank();

        // Agent executes buy: 600 USDT -> BNB
        vm.prank(agent);
        vault.executeBuy(user1, 600e18);

        (uint256 quote, uint256 base) = vault.getUserBalances(user1);
        assertEq(quote, 0);
        assertGt(base, 0); // should have some BNB
    }

    function test_Vault_ExecuteSell() public {
        // Setup: user deposits and agent buys
        vm.startPrank(user1);
        usdt.approve(address(vault), 600e18);
        vault.deposit(600e18);
        vm.stopPrank();

        vm.prank(agent);
        vault.executeBuy(user1, 600e18);

        (, uint256 baseBal) = vault.getUserBalances(user1);

        // Agent sells all BNB back to USDT
        vm.prank(agent);
        vault.executeSell(user1, baseBal);

        (uint256 quote, uint256 base) = vault.getUserBalances(user1);
        assertGt(quote, 0);
        assertEq(base, 0);
    }

    function test_Vault_OnlyAuthorized() public {
        vm.prank(user1);
        vm.expectRevert("Vault: not authorized");
        vault.executeBuy(user1, 100e18);
    }

    // ========== TradeRegistry Tests ==========

    function test_Registry_RecordTrade() public {
        vm.prank(agent);
        uint256 id = registry.recordTrade(
            user1,
            "BNB/USDT",
            true,
            600e18,
            1e18,
            600e18,
            "RSI oversold, whale outflow detected",
            82
        );

        assertEq(id, 0);
        assertEq(registry.totalTrades(), 1);
    }

    function test_Registry_GetRecentTrades() public {
        // Record 3 trades
        vm.startPrank(agent);
        registry.recordTrade(user1, "BNB/USDT", true, 600e18, 1e18, 600e18, "reason1", 80);
        registry.recordTrade(user1, "BNB/USDT", false, 1e18, 610e18, 610e18, "reason2", 75);
        registry.recordTrade(user1, "BNB/USDT", true, 300e18, 5e17, 600e18, "reason3", 90);
        vm.stopPrank();

        TradeRegistry.Trade[] memory recent = registry.getRecentTrades(2);
        assertEq(recent.length, 2);
        assertEq(recent[0].confidence, 75); // second trade
        assertEq(recent[1].confidence, 90); // third trade
    }

    function test_Registry_GetUserTrades() public {
        address user2 = address(0xB2);

        vm.startPrank(agent);
        registry.recordTrade(user1, "BNB/USDT", true, 600e18, 1e18, 600e18, "r1", 80);
        registry.recordTrade(user2, "BNB/USDT", true, 300e18, 5e17, 600e18, "r2", 70);
        registry.recordTrade(user1, "BNB/USDT", false, 1e18, 610e18, 610e18, "r3", 85);
        vm.stopPrank();

        TradeRegistry.Trade[] memory user1Trades = registry.getUserTrades(user1);
        assertEq(user1Trades.length, 2);

        TradeRegistry.Trade[] memory user2Trades = registry.getUserTrades(user2);
        assertEq(user2Trades.length, 1);
    }

    function test_Registry_OnlyAuthorized() public {
        vm.prank(user1);
        vm.expectRevert("TradeRegistry: not authorized");
        registry.recordTrade(user1, "BNB/USDT", true, 100e18, 1e17, 600e18, "test", 50);
    }
}
