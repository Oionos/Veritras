import { appEnvironment } from "@/config/runtime";

export default function TransactionLink({ hash }: { hash: string }) {
  if (!/^0x[0-9a-fA-F]{64}$/.test(hash))
    return <span>Invalid transaction reference</span>;
  return appEnvironment.chainId === 11155111 ? (
    <a
      className="break-all underline"
      href={`https://sepolia.etherscan.io/tx/${hash}`}
      target="_blank"
      rel="noopener noreferrer"
    >
      {hash}
    </a>
  ) : (
    <span className="break-all font-mono">{hash}</span>
  );
}
