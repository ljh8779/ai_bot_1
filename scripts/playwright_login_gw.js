const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({
    channel: 'msedge',
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();

  try {
    await page.goto('https://gw.zin.co.kr/login', {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });

    await page.fill('input[type="text"], input[name*="id" i], input[placeholder*="계정"]', process.env.GW_LOGIN_ID || '');
    await page.fill('input[type="password"], input[name*="pw" i], input[placeholder*="비밀번호"]', process.env.GW_LOGIN_PW || '');
    await page.click('button:has-text("로그인"), input[type="submit"], button[type="submit"]');

    await page.waitForTimeout(5000);

    const result = {
      url: page.url(),
      title: await page.title(),
      contentSnippet: (await page.locator('body').innerText()).slice(0, 1000),
    };

    await page.screenshot({ path: 'tmp/gw-after-login.png', fullPage: true });
    await context.storageState({ path: 'tmp/gw-storage-state.json' });

    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
