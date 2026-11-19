import { expect, test, type Page } from '@playwright/test';

// A finished run with a one-paragraph draft; only the fields the minutes page reads.
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
		items: [{ item_ref: '1', heading: 'Budget', paragraphs: [{ paragraph_id: '1.p1', kind: 'outcome', outcome_type: 'approved', text: 'The board approved the budget.', based_on: [] }] }],
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

const comparison = {
	run_id: 'run-1',
	similarity: 0.82,
	comments: [],
	items: [
		{ item_ref: 'header', heading: 'Header', status: 'unchanged', similarity: 1, words_added: 0, words_removed: 0, draft_text: '', final_text: '' },
		{ item_ref: '1', heading: 'Budget', status: 'edited', similarity: 0.8, words_added: 6, words_removed: 1, draft_text: '', final_text: '' }
	]
};

function feedback(verdict: string, reason: string | null) {
	const edited = verdict === 'edited';
	return {
		id: `f-${verdict}`,
		run_id: 'run-1',
		verdict,
		reward: { approved: 1, revision_requested: 0, edited: 0.82 }[verdict],
		reason,
		filename: edited ? 'final.docx' : null,
		comparison: edited ? comparison : null,
		edited_document_id: edited ? 'ed-1' : null,
		model: 'gemini-3.1-flash-lite',
		created_by: 'web-ui',
		created_at: '2026-11-10T10:00:00Z'
	};
}

/** Fake API: answers from `routes`, and records what the page sends. */
async function mockApi(page: Page) {
	const stored: ReturnType<typeof feedback>[] = [];
	const sent: unknown[] = [];
	await page.route('**/api/**', async (route) => {
		const request = route.request();
		const key = `${request.method()} ${new URL(request.url()).pathname}`;
		if (key === 'POST /api/drafts/run-1/feedback') {
			const body = request.postDataJSON();
			sent.push(body);
			stored.push(feedback(body.verdict, body.reason));
			return route.fulfill({ status: 201, json: stored.at(-1) });
		}
		if (key === 'POST /api/drafts/run-1/final') {
			sent.push(request.headers()['content-type']?.split(';')[0]);
			stored.push(feedback('edited', null));
			return route.fulfill({ status: 201, json: stored.at(-1) });
		}
		const routes: Record<string, unknown> = {
			'GET /api/drafts': [],
			'GET /api/drafts/run-1': run,
			'GET /api/drafts/run-1/feedback': stored,
			'GET /api/feedback/scores': [
				{ profile_slug: 'dess-standard', profile_version: 2, model: 'gemini-3.1-flash-lite', approvals: 3, revisions: 1, edits: 2, votes: 6, net: 2, approval_rate: 0.75, mean_similarity: 0.9, expected: 0.6 }
			]
		};
		if (key in routes) return route.fulfill({ json: routes[key] });
		return route.fulfill({ status: 404, json: { detail: `Not mocked: ${key}` } });
	});
	return sent;
}

test('a reviewer can approve the draft', async ({ page }) => {
	const sent = await mockApi(page);
	await page.goto('/drafts/run-1/minutes');

	await page.getByRole('button', { name: 'Approve' }).click();

	await expect(page.getByText('Approved', { exact: true })).toBeVisible();
	await expect(page.getByText('1 approval · 0 revisions')).toBeVisible();
	expect(sent).toEqual([{ verdict: 'approved', reason: null, by: 'web-ui' }]);
});

test('a revision request needs a reason', async ({ page }) => {
	const sent = await mockApi(page);
	await page.goto('/drafts/run-1/minutes');

	await page.getByRole('button', { name: 'Request revision' }).click();
	const send = page.getByRole('button', { name: 'Send' });
	await expect(send).toBeDisabled();

	await page.getByLabel('What needs revising?').fill('Item 1 leaves out the dissent.');
	await send.click();

	await expect(page.getByText('Revision requested')).toBeVisible();
	await expect(page.getByText('Item 1 leaves out the dissent.')).toBeVisible();
	expect(sent).toEqual([
		{ verdict: 'revision_requested', reason: 'Item 1 leaves out the dissent.', by: 'web-ui' }
	]);
});

test('an edited Word copy is uploaded and compared', async ({ page }) => {
	const sent = await mockApi(page);
	await page.goto('/drafts/run-1/minutes');

	await page.getByLabel('Edited Word file').setInputFiles('e2e/fixtures/final.docx');

	await expect(page.getByText('Edited copy uploaded')).toBeVisible();
	await expect(page.getByText('82% of the draft kept.')).toBeVisible();
	await expect(page.getByRole('link', { name: 'See what we learned from your edits' })).toBeVisible();
	expect(sent).toEqual(['multipart/form-data']);
});

test('the scores page ranks each setup', async ({ page }) => {
	await mockApi(page);
	await page.goto('/');
	await page.getByRole('link', { name: 'Draft scores' }).click();

	const row = page.getByRole('row', { name: /dess-standard v2/ });
	await expect(row).toContainText('gemini-3.1-flash-lite');
	await expect(row).toContainText('+2');
	await expect(row).toContainText('90%');
	await expect(row).toContainText('60%');
});
