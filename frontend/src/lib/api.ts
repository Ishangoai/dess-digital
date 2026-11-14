// Typed client for the minutes API (/api/drafts, /api/profiles). Mirrors backend/app/schemas.

export type DraftStatus =
	| 'analysing'
	| 'awaiting_mapping_review'
	| 'blocked'
	| 'drafting'
	| 'completed'
	| 'failed';

export const ASSOCIATIONS = [
	'primary',
	'related',
	'additional_business',
	'procedural',
	'uncertain'
] as const;
export type Association = (typeof ASSOCIATIONS)[number];

export interface LineRef {
	source_id: string;
	start: number;
	end: number;
}

export interface MeetingInfo {
	organisation: string | null;
	body_name: string | null;
	meeting_date: string | null;
	meeting_type: string | null;
	notes: string | null;
}

export interface AgendaItem {
	ref: string;
	heading: string;
	stated_purpose: string | null;
	purpose_kind: string;
	linked_papers: string[];
}

export interface AdditionalBusiness {
	key: string;
	heading: string;
}

export interface EvidenceSegment {
	segment_id: string;
	source: LineRef;
	item_ref: string | null;
	association: Association;
	summary: string;
	apparent_outcome: string | null;
}

export interface EvidenceMap {
	agenda_items: AgendaItem[];
	additional_business: AdditionalBusiness[];
	segments: EvidenceSegment[];
}

export interface EvidenceAnalysis extends EvidenceMap {
	sources: { source_id: string; description: string; limitations: string[] }[];
	essential_input_problems: { kind: string; description: string }[];
	uncertainties: {
		uncertainty_id: string;
		item_ref: string | null;
		description: string;
		competing_readings: string[];
		refs: LineRef[];
	}[];
}

export interface MinuteParagraph {
	paragraph_id: string;
	kind: string;
	outcome_type: string | null;
	text: string;
	based_on: string[];
}

export interface ClarificationQuestion {
	question_id: string;
	requirement_ids: string[];
	anchor_kind: 'paragraph' | 'item_heading' | 'meeting_heading';
	item_ref: string | null;
	paragraph_id: string | null;
	anchor_text: string | null;
	question: string;
}

export interface DraftMinutes {
	header: {
		title: string;
		meeting_date: string | null;
		time_and_place: string | null;
		present: string[];
		in_attendance: string[];
		apologies: string[];
	};
	items: { item_ref: string; heading: string; paragraphs: MinuteParagraph[] }[];
	actions: {
		action_id: string;
		text: string;
		owner: string | null;
		due: string | null;
		paragraph_id: string;
	}[];
	questions: ClarificationQuestion[];
	drafting_notes: string[];
}

export interface Finding {
	finding_id: string;
	category: string;
	significance: 'material' | 'minor';
	item_ref: string | null;
	issue: string;
	suggested_change: string | null;
}

export interface LLMCall {
	id: string;
	stage: string;
	provider: string;
	model: string;
	input_tokens: number;
	output_tokens: number;
	latency_ms: number;
	ok: boolean;
	error: string | null;
	created_at: string;
}

/** One call in full; null text means it was not stored (calls made before it was recorded). */
export interface LLMCallDetail extends LLMCall {
	system_prompt: string | null;
	prompt: string | null;
	output: string | null;
	raw_output: string | null;
}

export interface DraftRunSummary {
	id: string;
	status: DraftStatus;
	profile_slug: string;
	profile_version: number;
	meeting_info: MeetingInfo;
	title: string;
	created_at: string;
	completed_at: string | null;
}

export interface DraftRun extends DraftRunSummary {
	documents: { source_id: string; role: string; filename: string; line_count: number }[];
	analysis: EvidenceAnalysis | null;
	mapping: EvidenceMap | null;
	mapping_edited: boolean;
	draft: DraftMinutes | null;
	lint: string[];
	blocked_reasons: string[];
	error: string | null;
	error_stage: string | null;
	llm_calls: LLMCall[];
	usage_total: {
		input_tokens: number;
		output_tokens: number;
		total_tokens: number;
		latency_ms: number;
	};
	validation?: { findings: Finding[]; summary: string } | null;
	reconsideration?: {
		decisions: { finding_id: string; decision: string; reason: string }[];
	} | null;
}

export interface SegmentReview {
	segment_id: string;
	source: LineRef;
	item_ref: string | null;
	association: Association;
	summary: string;
	excerpt: string;
}

export interface MappingReview {
	status: DraftStatus;
	mapping: EvidenceMap;
	valid_item_refs: string[];
	segments: SegmentReview[];
	uncovered: LineRef[];
	uncovered_excerpts: string[];
}

export type VersionStatus = 'proposed' | 'reviewed' | 'confirmed' | 'withdrawn';

export interface ProfileSummary {
	slug: string;
	name: string;
	description: string | null;
	body_name: string | null;
	based_on_slug: string | null;
	active_version: number | null;
	latest_version: number | null;
}

export interface VersionSummary {
	version_number: number;
	status: VersionStatus;
	origin: string;
	content_sha256: string;
	change_summary: string | null;
	created_by: string | null;
	created_at: string;
	confirmed_at: string | null;
}

export interface ProfileDetail extends ProfileSummary {
	versions: VersionSummary[];
}

export interface ProfileDimension {
	code: string;
	title: string;
	default_standard: string;
}

export interface ProfileVersion extends VersionSummary {
	profile_slug: string;
	content: {
		name: string;
		description: string | null;
		hard_floors: string[];
		minuting_policy: ProfileDimension[];
		writing_style: ProfileDimension[];
	};
}

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

type Fetch = typeof fetch;

function detailText(detail: unknown): string {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail)) {
		// FastAPI validation errors
		return detail
			.map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : JSON.stringify(d)))
			.join('; ');
	}
	if (detail && typeof detail === 'object') {
		const d = detail as Record<string, unknown>;
		const list = d.mapping_errors ?? d.floor_violations;
		if (Array.isArray(list)) return list.map(String).join('; ');
	}
	return JSON.stringify(detail);
}

async function check(response: Response): Promise<Response> {
	if (response.ok) return response;
	let message = response.statusText;
	try {
		const body = await response.json();
		message = detailText(body.detail ?? body);
	} catch {
		// not JSON
	}
	if (response.status === 404 && message === 'Not Found') {
		message = 'Not found. Is MINUTES_ROUTES=true set on the API?';
	}
	throw new ApiError(response.status, `${response.status}: ${message}`);
}

async function json<T>(response: Promise<Response>): Promise<T> {
	return (await check(await response)).json();
}

function post(path: string, body?: unknown, f: Fetch = fetch) {
	return f(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
}

export const api = {
	listDrafts: (f: Fetch = fetch) => json<DraftRunSummary[]>(f('/api/drafts?limit=50')),
	getDraft: (id: string, f: Fetch = fetch) =>
		json<DraftRun>(f(`/api/drafts/${id}?debug=true`)),
	createDraft: (form: FormData) =>
		json<DraftRun>(fetch('/api/drafts', { method: 'POST', body: form })),
	getCalls: (id: string, f: Fetch = fetch) =>
		json<LLMCallDetail[]>(f(`/api/drafts/${id}/calls`)),
	getMapping: (id: string, f: Fetch = fetch) =>
		json<MappingReview>(f(`/api/drafts/${id}/mapping`)),
	retryAnalysis: (id: string) => json<DraftRun>(post(`/api/drafts/${id}/analyse`)),
	generate: (id: string, mapping: EvidenceMap | null) =>
		json<DraftRun>(post(`/api/drafts/${id}/generate`, mapping ?? undefined)),
	documentUrl: (id: string) => `/api/drafts/${id}/document.docx`,
	documentWithTemplate: async (id: string, template: File) => {
		const form = new FormData();
		form.append('template', template);
		const response = await check(
			await fetch(`/api/drafts/${id}/document`, { method: 'POST', body: form })
		);
		return response.blob();
	},

	listProfiles: (f: Fetch = fetch) => json<ProfileSummary[]>(f('/api/profiles')),
	getProfile: (slug: string, f: Fetch = fetch) =>
		json<ProfileDetail>(f(`/api/profiles/${slug}`)),
	getVersion: (slug: string, n: number, f: Fetch = fetch) =>
		json<ProfileVersion>(f(`/api/profiles/${slug}/versions/${n}`)),
	createVersion: (slug: string, content: unknown, change_summary: string) =>
		json<ProfileVersion>(
			post(`/api/profiles/${slug}/versions`, {
				content,
				change_summary: change_summary || null,
				created_by: 'web-ui'
			})
		),
	setStatus: (slug: string, n: number, status: VersionStatus) =>
		json<ProfileVersion>(
			post(`/api/profiles/${slug}/versions/${n}/status`, { status, by: 'web-ui' })
		)
};

export const STATUS_LABELS: Record<DraftStatus, string> = {
	analysing: 'Analysing',
	awaiting_mapping_review: 'Needs review',
	blocked: 'Blocked',
	drafting: 'Drafting',
	completed: 'Completed',
	failed: 'Failed'
};

export function errorText(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

export function formatDate(value: string | null): string {
	return value ? new Date(value).toLocaleString() : '-';
}

export function lineRef(r: LineRef): string {
	return r.start === r.end ? `${r.source_id}${r.start}` : `${r.source_id}${r.start}-${r.end}`;
}

export const ASSOCIATION_INFO: Record<Association, { label: string; hint: string }> = {
	primary: { label: 'Main discussion', hint: 'Where this agenda item was actually discussed' },
	related: { label: 'Related', hint: 'Touches on this item; the main discussion is elsewhere' },
	additional_business: { label: 'Not on agenda', hint: 'Business raised that was not on the agenda' },
	procedural: { label: 'Procedural', hint: 'Attendance, interests, quorum and similar' },
	uncertain: { label: 'Unsure', hint: 'The analysis could not tell which item this belongs to' }
};

export const SOURCE_ROLES: Record<string, string> = {
	agenda: 'Agenda',
	transcript: 'Transcript',
	notes: 'Notes',
	paper: 'Paper'
};

export function isRunning(status: DraftStatus): boolean {
	return status === 'analysing' || status === 'drafting';
}

export function formatDay(value: string): string {
	const d = new Date(value);
	const today = new Date();
	const days = Math.round((today.setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
	if (days === 0) return `Today, ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
	if (days === 1) return 'Yesterday';
	return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function fileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
	return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function plural(n: number, word: string): string {
	return `${n} ${word}${n === 1 ? '' : 's'}`;
}

/** Fired after a draft is created or changes stage, so the sidebar refreshes. */
export const DRAFTS_CHANGED = 'drafts:changed';
export function draftsChanged(): void {
	window.dispatchEvent(new Event(DRAFTS_CHANGED));
}

export const STAGE_INFO: Record<string, { label: string; about: string }> = {
	evidence: {
		label: 'Read the evidence',
		about: 'Maps the transcript and notes to the agenda items and records uncertainties.'
	},
	policy: {
		label: 'Select content',
		about: 'Applies the Minuting Policy (MP1 to MP9): what belongs in the record and what needs clarifying.'
	},
	style: {
		label: 'Write the minutes',
		about: 'Applies the Writing Style (WS1 to WS6) to write the draft and the questions.'
	},
	validation: {
		label: 'Check the draft',
		about: 'Independently checks the draft and questions against the evidence and the profile.'
	},
	reconsideration: {
		label: 'Reconsider',
		about: "Considers the check's findings once and revises the draft where they are supported."
	}
};

export function compact(n: number): string {
	return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
