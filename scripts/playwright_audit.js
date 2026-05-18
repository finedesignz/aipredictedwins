const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const SCREENSHOT_DIR = path.join(__dirname, '../data/screenshots');
if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

async function auditPage(page, url, name) {
  const errors = [];
  const networkFails = [];

  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(`CONSOLE ERROR: ${msg.text()}`);
    } else if (msg.type() === 'warning') {
      errors.push(`CONSOLE WARN: ${msg.text()}`);
    }
  });

  page.on('pageerror', err => {
    errors.push(`PAGE ERROR: ${err.message}`);
  });

  page.on('requestfailed', req => {
    networkFails.push(`NETWORK FAIL: ${req.method()} ${req.url()} — ${req.failure()?.errorText}`);
  });

  console.log(`\n=== Navigating to: ${url} ===`);

  try {
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    console.log(`HTTP Status: ${response?.status()} ${response?.statusText()}`);
  } catch (e) {
    console.log(`Navigation error: ${e.message}`);
  }

  // Wait a bit for any async rendering
  await page.waitForTimeout(3000);

  const screenshotPath = path.join(SCREENSHOT_DIR, `${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`Screenshot saved: ${screenshotPath}`);

  // Get page title and visible text
  const title = await page.title();
  console.log(`Page title: ${title}`);

  // Get all visible headings
  const headings = await page.$$eval('h1, h2, h3, nav a, [role="navigation"] a', els =>
    els.map(el => `${el.tagName}: ${el.textContent.trim().substring(0, 100)}`).filter(s => s.length > 5)
  );
  if (headings.length > 0) {
    console.log('Headings/Nav links:');
    headings.slice(0, 20).forEach(h => console.log(`  ${h}`));
  }

  // Get all links
  const links = await page.$$eval('a[href]', els =>
    els.map(el => ({ text: el.textContent.trim().substring(0, 50), href: el.href }))
       .filter(l => l.text.length > 0)
  );
  if (links.length > 0) {
    console.log('Links found:');
    links.slice(0, 20).forEach(l => console.log(`  "${l.text}" -> ${l.href}`));
  }

  // Check for error messages on page
  const errorTexts = await page.$$eval('[class*="error"], [class*="Error"], [role="alert"]', els =>
    els.map(el => el.textContent.trim().substring(0, 200))
  );
  if (errorTexts.length > 0) {
    console.log('Error elements on page:');
    errorTexts.forEach(e => console.log(`  ${e}`));
  }

  // Check for loading/skeleton states
  const loadingEls = await page.$$eval('[class*="loading"], [class*="skeleton"], [class*="spinner"]', els =>
    els.length
  );
  if (loadingEls > 0) {
    console.log(`Loading/skeleton elements still visible: ${loadingEls}`);
  }

  if (errors.length > 0) {
    console.log('\nConsole/Page errors:');
    errors.forEach(e => console.log(`  ${e}`));
  } else {
    console.log('No console errors detected.');
  }

  if (networkFails.length > 0) {
    console.log('\nNetwork failures:');
    networkFails.forEach(e => console.log(`  ${e}`));
  } else {
    console.log('No network failures detected.');
  }

  return { errors, networkFails, screenshotPath };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });

  const page = await context.newPage();

  // Audit main page
  const mainResult = await auditPage(page, 'https://app.aipredictedwins.com', 'main');

  // Look for navigation links to sub-pages
  const navLinks = await page.$$eval('nav a, [role="navigation"] a, aside a, .sidebar a', els =>
    els.map(el => ({ text: el.textContent.trim(), href: el.href })).filter(l => l.href && !l.href.startsWith('#'))
  );

  console.log('\n=== Sub-pages to visit ===');
  navLinks.forEach(l => console.log(`  "${l.text}" -> ${l.href}`));

  // Visit up to 5 sub-pages
  const visited = new Set(['https://app.aipredictedwins.com', 'https://app.aipredictedwins.com/']);
  let count = 0;
  for (const link of navLinks) {
    if (count >= 5) break;
    const href = link.href;
    if (visited.has(href)) continue;
    if (!href.includes('app.aipredictedwins.com')) continue;
    visited.add(href);

    const subPage = await context.newPage();
    const safeName = href.replace(/[^a-z0-9]/gi, '_').substring(0, 40);
    await auditPage(subPage, href, `subpage_${safeName}`);
    await subPage.close();
    count++;
  }

  await browser.close();
  console.log('\n=== Audit complete ===');
})();
