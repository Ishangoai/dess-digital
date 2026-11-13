import { error } from '@sveltejs/kit';
import { api, ApiError } from '#lib/api.ts';
import type { LayoutLoad } from './$types';

// Run ids are only known at runtime; the SPA fallback serves these pages.
export const prerender = false;

export const load: LayoutLoad = async ({ params, fetch, depends }) => {
	depends('app:run');
	try {
		return { run: await api.getDraft(params.id, fetch) };
	} catch (e) {
		if (e instanceof ApiError) error(e.status, e.message);
		throw e;
	}
};
