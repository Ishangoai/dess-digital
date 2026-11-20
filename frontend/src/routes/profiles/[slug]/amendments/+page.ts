import { error } from '@sveltejs/kit';
import { api, ApiError } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const prerender = false;

export const load: PageLoad = async ({ params, fetch, depends }) => {
	depends('app:amendments');
	try {
		const [profile, sets] = await Promise.all([
			api.getProfile(params.slug, fetch),
			api.listAmendmentSets(params.slug, fetch)
		]);
		return { profile, sets };
	} catch (e) {
		if (e instanceof ApiError) error(e.status, e.message);
		throw e;
	}
};
