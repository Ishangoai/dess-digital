import { redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// Send the user to the step the run is at.
export const load: PageLoad = async ({ parent, params }) => {
	const { run } = await parent();
	if (run.draft) redirect(307, `/drafts/${params.id}/minutes`);
	if (run.mapping) redirect(307, `/drafts/${params.id}/mapping`);
	return {};
};
