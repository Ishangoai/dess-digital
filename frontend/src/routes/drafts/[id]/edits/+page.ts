import { redirect } from '@sveltejs/kit';
import { api } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, params, fetch, depends }) => {
	depends('app:edits');
	const { run } = await parent();
	if (!run.draft) redirect(307, `/drafts/${params.id}`);
	return { edited: run.edited_document ? await api.getEdited(params.id, fetch) : null };
};
