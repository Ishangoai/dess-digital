import { redirect } from '@sveltejs/kit';
import { api } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, params, fetch, url, depends }) => {
	depends('app:edits');
	const { run } = await parent();
	if (!run.draft) redirect(307, `/drafts/${params.id}`);
	const edits = await api.listEdits(params.id, fetch);
	const chosen = url.searchParams.get('e') ?? edits[0]?.id;
	const review = chosen ? await api.getEdit(params.id, chosen, fetch) : null;
	return { edits, review };
};
