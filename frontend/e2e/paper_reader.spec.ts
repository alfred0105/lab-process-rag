import { expect, test } from '@playwright/test';

test('paper library opens the original equation PDF and evidence links to its source page', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Playwright paper reader fixture/ }).click();
  await page.getByRole('button', { name: '논문', exact: true }).click();
  await page.getByRole('button', { name: /A Test of a Physical Law/ }).click();

  const canvas = page.locator('canvas.paper-pdf-canvas');
  await expect(canvas).toBeVisible();
  await expect(page.getByLabel('페이지 번호')).toHaveValue('1');
  await expect.poll(() => canvas.evaluate(element => {
    const canvas = element as HTMLCanvasElement;
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    let dark = 0;
    for (let index = 0; index < pixels.length; index += 4) {
      if (pixels[index] < 100 && pixels[index + 1] < 100 && pixels[index + 2] < 100) dark += 1;
    }
    return dark;
  })).toBeGreaterThan(100);
  await page.screenshot({ path: '/tmp/lab-process-paper-reader.png', fullPage: true });

  await page.getByRole('button', { name: /근거/ }).click();
  await page.getByRole('button', { name: /Recorded evidence from page two/ }).click();
  await expect(page.getByLabel('페이지 번호')).toHaveValue('2');
  await page.getByRole('button', { name: '이전 페이지' }).click();
  await expect(page.getByLabel('페이지 번호')).toHaveValue('1');
});
