import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const outputDir = path.resolve(here, "../../deliverables");
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const errors = [];

async function attachErrorCapture(page, label) {
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(`${label} console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => {
    errors.push(`${label} pageerror: ${error.message}`);
  });
}

async function askQuestion(page, question) {
  await page.getByLabel("你想从年报中确认什么？").fill(question);
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.getByText("答案出处").waitFor({ timeout: 120_000 });
  await page.getByText("168,838,102,514.79", { exact: false }).first().waitFor({
    timeout: 30_000,
  });
}

const desktop = await browser.newPage({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});
await attachErrorCapture(desktop, "desktop");
await desktop.goto("http://127.0.0.1:5173/", {
  waitUntil: "networkidle",
});
await desktop.getByText("知识库在线").waitFor({ timeout: 120_000 });
await askQuestion(desktop, "贵州茅台2025年营业收入是多少？");

const desktopOverflow = await desktop.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
await desktop.screenshot({
  path: path.join(outputDir, "screenshot-qa-desktop.png"),
  fullPage: true,
});

await desktop.getByRole("tab", { name: "召回详情" }).click();
await desktop.getByText("查看召回信息").first().click();
await desktop.getByText("混合得分").first().waitFor();
await desktop.getByRole("tab", { name: "回答" }).click();

const mobile = await browser.newPage({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 1,
});
await attachErrorCapture(mobile, "mobile");
await mobile.goto("http://127.0.0.1:5173/", {
  waitUntil: "networkidle",
});
await mobile.getByText("知识库在线").waitFor({ timeout: 120_000 });
await askQuestion(mobile, "贵州茅台2025年营业收入是多少？");
const mobileOverflow = await mobile.evaluate(
  () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
);
await mobile.screenshot({
  path: path.join(outputDir, "screenshot-qa-mobile.png"),
  fullPage: true,
});

await browser.close();

if (desktopOverflow > 1 || mobileOverflow > 1) {
  errors.push(
    `horizontal overflow desktop=${desktopOverflow}px mobile=${mobileOverflow}px`,
  );
}
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(
  JSON.stringify(
    {
      status: "pass",
      desktopScreenshot: path.join(outputDir, "screenshot-qa-desktop.png"),
      mobileScreenshot: path.join(outputDir, "screenshot-qa-mobile.png"),
      desktopOverflow,
      mobileOverflow,
      consoleErrors: errors.length,
    },
    null,
    2,
  ),
);
