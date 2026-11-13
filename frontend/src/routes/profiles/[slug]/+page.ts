import { error } from '@sveltejs/kit';
import { api, ApiError } from '#lib/api.ts';
import type { PageLoad } from './$types';

export const prerender = false;

export const load: PageLoad = async ({ params, fetch, url, depends }) => {
	depends('app:profile');
	try {
		const profile = await api.getProfile(params.slug, fetch);
		const requested = Number(url.searchParams.get('v'));
		const number = requested || profile.active_version || profile.latest_version;
		const version = number ? await api.getVersion(params.slug, number, fetch) : null;
		return { profile, version };
	} catch (e) {
		if (e instanceof ApiError) error(e.status, e.message);
		throw e;
	}
};
