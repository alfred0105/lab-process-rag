import { expect, test } from '@playwright/test';

test('isolated sandbox trains a GP, ranks candidates, and compares Branin baselines', async ({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:/Playwright isolated synthetic topic/}).click();
  await page.getByRole('button',{name:'기타',exact:true}).click();
  await page.getByRole('menuitem',{name:'Optimization'}).click();
  const trainResponse=page.waitForResponse(response=>response.url().includes('/optimization/models/train')&&response.request().method()==='POST');
  const recommendation=page.waitForResponse(response=>response.url().includes('/optimization/models/')&&response.url().endsWith('/recommend'));
  await page.getByRole('button',{name:'GP 학습 후 다음 조건 추천'}).click();
  const trained=await trainResponse;
  expect(trained.ok()).toBeTruthy();
  const model=await trained.json();
  expect(model.mode).toBe('sandbox');
  expect(model.config.sample_count).toBe(24);
  const result=await recommendation;
  expect(result.ok()).toBeTruthy();
  const payload=await result.json();
  expect(payload.candidates).toHaveLength(5);
  expect(payload.approval_status).toBe('PENDING_RESEARCHER_REVIEW');
  await expect(page.getByText('연구자 검토 필요').first()).toBeVisible();
  await expect(page.getByText(/Branin \(synthetic sandbox\)/)).toBeVisible({timeout:90_000});
  await expect(page.getByText(/GP \+ EI 중앙 최선값/)).toBeVisible();

  await page.getByRole('combobox').first().selectOption('noisy');
  const stage2Response=page.waitForResponse(response=>response.url().includes('/optimization/sandbox/benchmark/stage2')&&response.request().method()==='POST');
  await page.getByRole('button',{name:'벤치마크 실행'}).click();
  const stage2=await stage2Response;
  expect(stage2.ok()).toBeTruthy();
  const stage2Payload=await stage2.json();
  expect(stage2Payload.noisy.policies.gp_noisy_ei.runs).toBe(5);
  await expect(page.getByText('Phase 4 · Stage 2 합성 벤치마크')).toBeVisible();
  await expect(page.getByRole('heading',{name:/노이즈 최적화/})).toBeVisible();
});
