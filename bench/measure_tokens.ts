import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const usage = `Usage:
  tsx bench/measure_tokens.ts --text "your text here"
  tsx bench/measure_tokens.ts --file path/to/input.txt

Estimates tokens with the repo heuristic:
  int(words * 1.3)
`;

export const estimateTokens = (text: string): number => {
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  return Math.floor(words * 1.3);
};

const getArg = (args: string[], name: string): string | undefined => {
  const index = args.indexOf(name);
  if (index === -1) {
    return undefined;
  }
  return args[index + 1];
};

const runCli = (): void => {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(usage);
    return;
  }

  const inlineText = getArg(args, "--text");
  const filePath = getArg(args, "--file");
  if (!inlineText && !filePath) {
    console.error("Provide --text or --file.\n");
    console.error(usage);
    process.exitCode = 1;
    return;
  }

  const text = inlineText ?? fs.readFileSync(path.resolve(filePath!), "utf8");
  const tokens = estimateTokens(text);
  console.log(JSON.stringify({ tokens, words: text.trim() ? text.trim().split(/\s+/).length : 0 }, null, 2));
};

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  runCli();
}
