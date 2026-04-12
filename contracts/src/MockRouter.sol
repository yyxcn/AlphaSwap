// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract MockRouter is Ownable {
    // rate: tokenA -> tokenB, stored as amountB * 1e18 per 1 tokenA (in base units)
    // e.g., 1 BNB (18 dec) = 600 USDT (18 dec) => rate = 600e18
    mapping(address => mapping(address => uint256)) public rates;

    constructor() Ownable(msg.sender) {}

    function setRate(address tokenA, address tokenB, uint256 rate) external onlyOwner {
        rates[tokenA][tokenB] = rate;
        // auto set inverse
        if (rate > 0) {
            rates[tokenB][tokenA] = (1e36) / rate;
        }
    }

    function getRate(address tokenA, address tokenB) external view returns (uint256) {
        return rates[tokenA][tokenB];
    }

    /// @notice PancakeSwap V2 Router compatible interface
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts) {
        require(block.timestamp <= deadline, "MockRouter: EXPIRED");
        require(path.length == 2, "MockRouter: INVALID_PATH");

        address tokenIn = path[0];
        address tokenOut = path[1];
        uint256 rate = rates[tokenIn][tokenOut];
        require(rate > 0, "MockRouter: NO_RATE");

        uint256 amountOut = (amountIn * rate) / 1e18;
        require(amountOut >= amountOutMin, "MockRouter: INSUFFICIENT_OUTPUT");

        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenOut).transfer(to, amountOut);

        amounts = new uint256[](2);
        amounts[0] = amountIn;
        amounts[1] = amountOut;
    }

    /// @notice View function to get expected output amount
    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external
        view
        returns (uint256[] memory amounts)
    {
        require(path.length == 2, "MockRouter: INVALID_PATH");
        uint256 rate = rates[path[0]][path[1]];
        require(rate > 0, "MockRouter: NO_RATE");

        amounts = new uint256[](2);
        amounts[0] = amountIn;
        amounts[1] = (amountIn * rate) / 1e18;
    }
}
