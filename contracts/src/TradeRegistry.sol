// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

contract TradeRegistry is Ownable {
    struct Trade {
        address user;
        string pair;
        bool isBuy;
        uint256 amountIn;
        uint256 amountOut;
        uint256 price;
        string aiReasoning;
        uint8 confidence;
        uint256 timestamp;
    }

    Trade[] public trades;
    mapping(address => uint256[]) public userTradeIds;
    mapping(address => bool) public authorized;

    event TradeRecorded(
        uint256 indexed tradeId,
        address indexed user,
        bool isBuy,
        uint256 amountIn,
        uint256 amountOut,
        uint256 price,
        uint8 confidence
    );

    modifier onlyAuthorized() {
        require(authorized[msg.sender], "TradeRegistry: not authorized");
        _;
    }

    constructor() Ownable(msg.sender) {}

    function setAuthorized(address agent, bool status) external onlyOwner {
        authorized[agent] = status;
    }

    function recordTrade(
        address user,
        string calldata pair,
        bool isBuy,
        uint256 amountIn,
        uint256 amountOut,
        uint256 price,
        string calldata aiReasoning,
        uint8 confidence
    ) external onlyAuthorized returns (uint256 tradeId) {
        tradeId = trades.length;
        trades.push(Trade({
            user: user,
            pair: pair,
            isBuy: isBuy,
            amountIn: amountIn,
            amountOut: amountOut,
            price: price,
            aiReasoning: aiReasoning,
            confidence: confidence,
            timestamp: block.timestamp
        }));
        userTradeIds[user].push(tradeId);

        emit TradeRecorded(tradeId, user, isBuy, amountIn, amountOut, price, confidence);
    }

    function getRecentTrades(uint256 count) external view returns (Trade[] memory) {
        uint256 total = trades.length;
        if (count > total) count = total;

        Trade[] memory result = new Trade[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = trades[total - count + i];
        }
        return result;
    }

    function getUserTrades(address user) external view returns (Trade[] memory) {
        uint256[] memory ids = userTradeIds[user];
        Trade[] memory result = new Trade[](ids.length);
        for (uint256 i = 0; i < ids.length; i++) {
            result[i] = trades[ids[i]];
        }
        return result;
    }

    function totalTrades() external view returns (uint256) {
        return trades.length;
    }
}
