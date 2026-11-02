import { expect, test } from '@playwright/test';

test('dark workstation keeps topic context while navigating analysis and campaign tools', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Playwright isolated synthetic topic/ }).click();

  await expect(page.getByLabel('공정 캔버스')).toBeVisible();
  await expect(page.getByText('Playwright isolated synthetic topic', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '공정 흐름' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('이 방법 버전에는 공정 단계가 없습니다')).toBeVisible();

  await page.getByRole('button', { name: '측정·분석' }).click();
  await expect(page.getByRole('heading', { name: '측정·분석' })).toBeVisible();
  await expect(page.getByText('저장형 과학 분석 흐름')).toBeVisible();

  await page.locator('.workstation-nav button').filter({ hasText: '캠페인' }).click();
  await expect(page.getByRole('heading', { name: '캠페인' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '실험 최적화 캠페인' })).toBeVisible();
  await expect(page.getByText('실험 기록 (선택)')).toBeVisible();
});

test('method canvas shows saved run conditions in the inspector and highlights API comparison results', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Playwright process canvas fixture/ }).click();

  await expect(page.getByLabel('공정 캔버스')).toBeVisible();
  await page.getByLabel('공정 방법 선택').selectOption({ label: 'Canvas test method' });
  await expect(page.locator('.react-flow__node-default')).toHaveCount(2);
  await page.getByLabel('Run A').selectOption({ label: 'E2E-CANVAS-A · Canvas run A' });
  await page.locator('.react-flow__node-default').first().click();
  await page.getByRole('tab', { name: '조건' }).click();
  await expect(page.locator('.workstation-inspector').getByText('stir speed', { exact: true }).first()).toBeVisible();
  await expect(page.locator('.workstation-inspector').getByText('300 rpm', { exact: true })).toBeVisible();

  const comparisonResponse = page.waitForResponse(response => response.url().includes('/experiments/') && response.url().includes('/compare/') && response.url().includes('comparison_mode=same_version'));
  await page.getByLabel('Run B 비교').selectOption({ label: 'E2E-CANVAS-B · Canvas run B' });
  const response = await comparisonResponse;
  expect(response.ok()).toBeTruthy();
  const comparison = await response.json();
  expect(comparison.different_variables).toHaveLength(1);
  await expect(page.locator('.react-flow__node-default.has-difference')).toHaveCount(1);
  await expect(page.locator('.workstation-inspector').getByText(/300 rpm → 450 rpm/)).toBeVisible();
});
