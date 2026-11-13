import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, params }) => {
	const { run } = await parent();
	if (!run.draft) redirect(307, `/drafts/${params.id}`);
	return {};
};
