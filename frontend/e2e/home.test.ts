import { expect, test, type Page } from '@playwright/test';

async function signIn(page: Page) {
	await page.route('**/api/auth/login', async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ status: 'ok' })
		});
	});
	await page.getByPlaceholder('Username').fill('admin');
	await page.getByPlaceholder('Password').fill('admin');
	await page.getByRole('button', { name: 'Sign In' }).click();
}

test('home page opens on new minutes', async ({ page }) => {
	await page.goto('/');
	await signIn(page);
	await expect(page.getByRole('heading', { name: 'New minutes' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'New minutes' })).toBeVisible();
});

test('agenda and transcript are required; notes and papers are tucked away', async ({ page }) => {
	await page.goto('/drafts/new');
	await signIn(page);
	await expect(page.getByLabel('Agenda')).toBeAttached();
	await expect(page.getByLabel('Transcript')).toBeAttached();
	await expect(page.getByRole('button', { name: 'Analyse meeting' })).toBeDisabled();
	await expect(page.getByLabel('Meeting notes')).toHaveCount(0);
	await page.getByRole('button', { name: 'Add meeting notes or papers' }).click();
	await expect(page.getByLabel('Meeting notes')).toBeAttached();
});
