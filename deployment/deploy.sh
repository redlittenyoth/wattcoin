#!/bin/bash

# WattCoin Deployment Script
# Usage: ./deploy.sh [devnet|mainnet]

set -e

NETWORK=${1:-devnet}
PROGRAM_ID="WATT1111111111111111111111111111111111111111"

echo "🔧 Deploying WattCoin to $NETWORK..."

# Validate network
if [ "$NETWORK" != "devnet" ] && [ "$NETWORK" != "mainnet" ]; then
    echo "❌ Invalid network. Use 'devnet' or 'mainnet'"
    exit 1
fi

# Check required tools
command -v anchor >/dev/null 2>&1 || { echo "❌ Anchor CLI required. Install: https://project-serum.github.io/anchor/getting-started/installation.html"; exit 1; }
command -v solana >/dev/null 2>&1 || { echo "❌ Solana CLI required. Install: https://docs.solana.com/cli/install-solana-cli-tools"; exit 1; }

# Set Solana config
echo "⚙️  Configuring Solana CLI for $NETWORK..."
if [ "$NETWORK" = "mainnet" ]; then
    solana config set --url https://api.mainnet-beta.solana.com
else
    solana config set --url https://api.devnet.solana.com
fi

# Build the program
echo "🔨 Building WattCoin smart contract..."
cd contracts/wattcoin
anchor build

# Deploy to network
echo "🚀 Deploying to $NETWORK..."
anchor deploy --provider.cluster $NETWORK

# Verify deployment
echo "✅ Verifying deployment..."
DEPLOYED_ID=$(solana program show --programs | grep wattcoin | awk '{print $1}')
echo "Program deployed at: $DEPLOYED_ID"

# Initialize token if on devnet (for testing)
if [ "$NETWORK" = "devnet" ]; then
    echo "🧪 Initializing test token on devnet..."
    anchor run initialize-devnet
fi

echo "✨ WattCoin deployment complete!"
echo ""
echo "📋 Next Steps:"
echo "1. Update frontend config with program ID: $DEPLOYED_ID"
echo "2. Fund liquidity pool on Pump.fun"
echo "3. Activate AI platform webhooks"
echo "4. Monitor burn rate and transaction volume"

if [ "$NETWORK" = "mainnet" ]; then
    echo ""
    echo "🚨 MAINNET DEPLOYMENT COMPLETE"
    echo "💰 Budget Used: ~$2000 (deployment + initial liquidity)"
    echo "📊 Dashboard: https://wattcoin.dev/dashboard"
    echo "🔍 Explorer: https://explorer.solana.com/address/$DEPLOYED_ID"
fi