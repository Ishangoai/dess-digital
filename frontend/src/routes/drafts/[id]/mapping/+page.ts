import { redirect } from '@sveltejs/kit';
import { api } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, params, fetch }) => {
	const { run } = await parent();
	if (!run.mapping) redirect(307, `/drafts/${params.id}`);
	return { review: await api.getMapping(params.id, fetch) };
};
