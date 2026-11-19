import { expect, test, type Page } from '@playwright/test';

// A finished run; only the fields the pages read.
const run = {
	id: 'run-1',
	status: 'completed',
	profile_slug: 'dess-standard',
	profile_version: 2,
	meeting_info: { organisation: null, body_name: null, meeting_date: null, meeting_type: null, notes: null },
	title: 'Northbridge Trust Board',
	created_at: '2026-11-10T09:00:00Z',
	completed_at: '2026-11-10T09:05:00Z',
	documents: [],
	analysis: null,
	mapping: { agenda_items: [], additional_business: [], segments: [] },
	mapping_edited: false,
	draft: {
		header: { title: 'Minutes of the Board', meeting_date: null, time_and_place: null, present: [], in_attendance: [], apologies: [] },
		items: [{ item_ref: '4', heading: 'Roof contract', paragraphs: [] }],
		actions: [],
		questions: [],
		drafting_notes: []
	},
	lint: [],
	blocked_reasons: [],
	error: null,
	error_stage: null,
	llm_calls: [],
	usage_total: { input_tokens: 0, output_tokens: 0, total_tokens: 0, latency_ms: 0 }
};

function row(id: string, status: string, original: string, final: string, diff: object[], labels: object[] = []) {
	return {
		id, position: 0, item_ref: '4', original_item_ref: '4', original_n: 1, paragraph_id: '4.p1',
		role: 'body', status, similarity: 0.8, original_text: original, final_text: final, diff,
		tracked: [], comment_ids: [], labels
	};
}

const label = {
	id: 'l-1', hunk: 0, before: 'The Board approved', after: 'It was resolved that', source: 'model',
	kind: 'wording_style', dimensions: ['WS5'], cause: 'profile_silent', support: 'not_applicable',
	evidence: [{ source_id: 'T', start: 12, end: 13 }], profile_basis: null,
	reason: 'House phrasing for resolutions.', pattern: 'resolution wording', route: 'candidate'
};

function review(classified: boolean) {
	return {
		id: 'ed-1', filename: 'final.docx', created_at: '2026-11-10T10:00:00Z', created_by: 'web-ui',
		similarity: 0.82, export_id: 'ex-1', original_recreated: false,
		counts: { unchanged: 1, changed: 1 }, classified_at: classified ? '2026-11-10T10:01:00Z' : null,
		classifying: !classified,
		sections: [{ item_ref: 'header', heading: 'Header', added: false }, { item_ref: '4', heading: 'Roof contract', added: false }],
		paragraphs: [
			row('r-1', 'changed', 'The Board approved phase one.', 'It was resolved that phase one be approved.', [
				{ op: 'delete', text: 'The Board approved ' },
				{ op: 'insert', text: 'It was resolved that ' },
				{ op: 'equal', text: 'phase one' },
				{ op: 'insert', text: ' be approved' },
				{ op: 'equal', text: '.' }
			], classified ? [label] : []),
			row('r-2', 'unchanged', 'Priya Shah remained concerned.', 'Priya Shah remained concerned.', [
				{ op: 'equal', text: 'Priya Shah remained concerned.' }
			])
		],
		comments: [],
		answers: [{ question_id: 'Q1', question: 'Who will write to tenants?', reply: 'The Company Secretary.', author: 'Jane' }],
		findings: classified
			? [{ key: 'k', pattern: "Write approvals as 'It was resolved that'", kind: 'wording_style', dimensions: ['WS5'], cause: 'profile_silent',
				route: 'candidate', count: 2, items: ['4', '7'], reason: 'House phrasing for resolutions.', profile_basis: null,
				evidence: [], label_ids: ['l-1'] }]
			: [],
		classify_error: null
	};
}

/** Fake API. The upload is still being classified on the first visit, and done after that. */
async function mockApi(page: Page) {
	let visits = 0;
	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const key = `${request.method()} ${new URL(request.url()).pathname}`;
		if (key === 'GET /api/drafts/run-1/edits/ed-1') return route.fulfill({ json: review(visits++ > 0) });
		const routes: Record<string, unknown> = {
			'GET /api/drafts': [],
			'GET /api/drafts/run-1': run,
			'GET /api/drafts/run-1/edits': [review(false)]
		};
		if (key in routes) return route.fulfill({ json: routes[key] });
		return route.fulfill({ status: 404, json: { detail: `Not mocked: ${key}` } });
	});
}

test('the page opens on a short summary of what was learned', async ({ page }) => {
	await mockApi(page);
	await page.goto('/drafts/run-1/edits');

	await expect(page.getByText('82%')).toBeVisible();
	await expect(page.getByText('Working out what we learned from your edits...')).toBeVisible();

	const learned = page.getByLabel('What we learned');
	await expect(learned.getByText('Remembered as house style')).toBeVisible({ timeout: 10_000 });
	await expect(learned.getByText("Write approvals as 'It was resolved that'")).toBeVisible();
	await expect(learned.getByText('×2')).toBeVisible();
	await expect(learned.getByText('The Company Secretary.')).toBeVisible();
	await expect(page.locator('del')).toHaveCount(0); // the details stay hidden
});

test('all changes can still be shown, side by side with their labels', async ({ page }) => {
	await mockApi(page);
	await page.goto('/drafts/run-1/edits');
	await expect(page.getByText('Remembered as house style')).toBeVisible({ timeout: 10_000 });

	await page.getByRole('button', { name: /Show all changes/ }).click();

	await expect(page.locator('del', { hasText: 'The Board approved' })).toBeVisible();
	await expect(page.locator('ins', { hasText: 'It was resolved that' })).toBeVisible();
	await expect(page.getByText('Priya Shah remained concerned.')).toHaveCount(0); // unchanged hidden
	await page.getByText('Profile silent or says otherwise · WS5 · Wording or style', { exact: true }).click();
	await expect(page.getByText('"The Board approved" → "It was resolved that"')).toBeVisible();
	await expect(page.getByText('T12-13')).toBeVisible();

	await page.getByLabel('Only show changed paragraphs').uncheck();
	await expect(page.getByText('Priya Shah remained concerned.').first()).toBeVisible();
});
