import { expect, test } from '@playwright/test';

test('unified workspace carries the selected research topic through process, analysis, and campaign views', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Playwright isolated synthetic topic/ }).click();

  await expect(page.getByRole('heading', { name: '통합 연구 작업공간' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Playwright isolated synthetic topic' })).toBeVisible();
  await expect(page.getByRole('button', { name: /실험·공정/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /측정·분석/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /판단·추천/ })).toBeVisible();

  await page.getByRole('button', { name: /측정·분석/ }).click();
  await expect(page.getByRole('heading', { name: '선택한 실험의 측정과 분석' })).toBeVisible();
  await expect(page.getByText('저장형 과학 분석 흐름')).toBeVisible();

  await page.getByRole('button', { name: /판단·추천/ }).click();
  await expect(page.getByRole('tab', { name: 'AI 판단' })).toBeVisible();
  await page.getByRole('tab', { name: '캠페인·검토' }).click();
  await expect(page.getByRole('heading', { name: '실험 최적화 캠페인' })).toBeVisible();
  await expect(page.getByLabel('실험 기록 (필수)')).toBeVisible();
});
