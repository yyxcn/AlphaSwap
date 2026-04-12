// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

interface IRouter {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

contract Vault is Ownable {
    using SafeERC20 for IERC20;

    IERC20 public quoteToken;   // USDT
    IERC20 public baseToken;    // BNB (MockBNB)
    IRouter public router;

    mapping(address => uint256) public quoteBalances;  // user -> USDT balance
    mapping(address => uint256) public baseBalances;   // user -> BNB balance
    mapping(address => bool) public authorized;        // agent addresses

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event BuyExecuted(address indexed user, uint256 usdtIn, uint256 bnbOut);
    event SellExecuted(address indexed user, uint256 bnbIn, uint256 usdtOut);

    modifier onlyAuthorized() {
        require(authorized[msg.sender], "Vault: not authorized");
        _;
    }

    constructor(
        address _quoteToken,
        address _baseToken,
        address _router
    ) Ownable(msg.sender) {
        quoteToken = IERC20(_quoteToken);
        baseToken = IERC20(_baseToken);
        router = IRouter(_router);
    }

    function setAuthorized(address agent, bool status) external onlyOwner {
        authorized[agent] = status;
    }

    function deposit(uint256 amount) external {
        quoteToken.safeTransferFrom(msg.sender, address(this), amount);
        quoteBalances[msg.sender] += amount;
        emit Deposited(msg.sender, amount);
    }

    function withdraw(uint256 amount) external {
        require(quoteBalances[msg.sender] >= amount, "Vault: insufficient balance");
        quoteBalances[msg.sender] -= amount;
        quoteToken.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    function executeBuy(address user, uint256 amountIn) external onlyAuthorized {
        require(quoteBalances[user] >= amountIn, "Vault: insufficient USDT");
        quoteBalances[user] -= amountIn;

        quoteToken.approve(address(router), amountIn);

        address[] memory path = new address[](2);
        path[0] = address(quoteToken);
        path[1] = address(baseToken);

        uint256[] memory amounts = router.swapExactTokensForTokens(
            amountIn,
            0, // amountOutMin = 0 for demo
            path,
            address(this),
            block.timestamp + 300
        );

        baseBalances[user] += amounts[1];
        emit BuyExecuted(user, amountIn, amounts[1]);
    }

    function executeSell(address user, uint256 amountIn) external onlyAuthorized {
        require(baseBalances[user] >= amountIn, "Vault: insufficient BNB");
        baseBalances[user] -= amountIn;

        baseToken.approve(address(router), amountIn);

        address[] memory path = new address[](2);
        path[0] = address(baseToken);
        path[1] = address(quoteToken);

        uint256[] memory amounts = router.swapExactTokensForTokens(
            amountIn,
            0, // amountOutMin = 0 for demo
            path,
            address(this),
            block.timestamp + 300
        );

        quoteBalances[user] += amounts[1];
        emit SellExecuted(user, amountIn, amounts[1]);
    }

    function getUserBalances(address user) external view returns (uint256 quote, uint256 base) {
        quote = quoteBalances[user];
        base = baseBalances[user];
    }
}
