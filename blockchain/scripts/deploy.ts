import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

async function main() {
  const chainId = (await ethers.provider.getNetwork()).chainId;
  if (process.env.TESTING_DEPLOYMENT === "true" && chainId !== 31337n) {
    throw new Error("Local testing deployment must use chain 31337");
  }
  const outputPath = process.env.DEPLOYMENT_OUTPUT || path.join(__dirname, "..", "deployed-contracts.json");
  if (process.env.TESTING_DEPLOYMENT === "true" && fs.existsSync(outputPath)) {
    const previous = JSON.parse(fs.readFileSync(outputPath, "utf8"));
    if (Number(previous.chainId) !== 31337) throw new Error("Invalid local deployment manifest");
    const registryCode = await ethers.provider.getCode(previous.contracts.ProductRegistry);
    const trackerCode = await ethers.provider.getCode(previous.contracts.ShipmentTracker);
    if (registryCode !== "0x" && trackerCode !== "0x") {
      const tracker = await ethers.getContractAt("ShipmentTracker", previous.contracts.ShipmentTracker);
      if ((await tracker.productRegistry()).toLowerCase() !== previous.contracts.ProductRegistry.toLowerCase()) {
        throw new Error("Local contract deployment does not match its manifest");
      }
      console.log("Reusing isolated local contract deployment");
      return;
    }
  }
  const [deployer] = await ethers.getSigners();
  console.log("Deploying contracts with the account:", deployer.address);

  const ProductRegistry = await ethers.getContractFactory("ProductRegistry");
  const productRegistry = await ProductRegistry.deploy();
  await productRegistry.waitForDeployment();
  const productRegistryAddress = await productRegistry.getAddress();
  const registryReceipt = await productRegistry.deploymentTransaction()!.wait();
  console.log("ProductRegistry deployed to:", productRegistryAddress);

  const ShipmentTracker = await ethers.getContractFactory("ShipmentTracker");
  const shipmentTracker = await ShipmentTracker.deploy(productRegistryAddress);
  await shipmentTracker.waitForDeployment();
  const shipmentTrackerAddress = await shipmentTracker.getAddress();
  const trackerReceipt = await shipmentTracker.deploymentTransaction()!.wait();
  console.log("ShipmentTracker deployed to:", shipmentTrackerAddress);

  const deploymentInfo = {
    network: (await ethers.provider.getNetwork()).name,
    chainId: (await ethers.provider.getNetwork()).chainId.toString(),
    deployer: deployer.address,
    startBlock: Math.min(registryReceipt!.blockNumber, trackerReceipt!.blockNumber),
    deploymentBlocks: {
      ProductRegistry: registryReceipt!.blockNumber,
      ShipmentTracker: trackerReceipt!.blockNumber,
    },
    contracts: {
      ProductRegistry: productRegistryAddress,
      ShipmentTracker: shipmentTrackerAddress,
    },
    timestamp: new Date().toISOString(),
  };

  fs.writeFileSync(outputPath, JSON.stringify(deploymentInfo, null, 2));
  console.log("Deployment info saved to:", outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
