import { expect, test } from '@playwright/test';

test('home page renders', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dess Digital Minutes' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'New draft' }).first()).toBeVisible();
});

test('new draft page renders the upload form', async ({ page }) => {
	await page.goto('/drafts/new');
	await expect(page.getByRole('heading', { name: 'New draft' })).toBeVisible();
	await expect(page.getByLabel('Agenda (required)')).toBeVisible();
});
