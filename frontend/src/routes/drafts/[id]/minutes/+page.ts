import { redirect } from '@sveltejs/kit';
import { api } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, params, fetch, depends }) => {
	depends('app:feedback');
	const { run } = await parent();
	if (!run.draft) redirect(307, `/drafts/${params.id}`);
	return { feedback: await api.getFeedback(params.id, fetch) };
};
