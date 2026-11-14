// Splits stored prompts into labelled sections for the AI activity view.
// Mirrors backend/app/minutes/prompts.py: the message is a series of top-level <tag> blocks.

export type SectionKind = 'instructions' | 'meeting' | 'evidence' | 'guidance' | 'earlier' | 'task';

export interface PromptSection {
	key: string;
	kind: SectionKind;
	title: string;
	detail?: string;
	text: string;
}

const EVIDENCE_TAGS: Record<string, string> = {
	agenda: 'Agenda',
	transcript: 'Transcript',
	notes: 'Meeting notes',
	paper: 'Paper'
};

const TAGS: Record<string, { kind: SectionKind; title: string }> = {
	meeting_information: { kind: 'meeting', title: 'Meeting details' },
	stage_guidance: { kind: 'guidance', title: 'Stage guidance from the profile' },
	confirmed_evidence_map: { kind: 'earlier', title: 'Confirmed mapping' },
	evidence_notes: { kind: 'earlier', title: 'Notes from reading the evidence' },
	selection: { kind: 'earlier', title: 'Content selected (step 2)' },
	draft: { kind: 'earlier', title: 'Draft minutes (step 3)' },
	automated_checks: { kind: 'earlier', title: 'Automated checks' },
	findings: { kind: 'earlier', title: 'Findings from the check (step 4)' },
	task: { kind: 'task', title: 'Task' }
};

const BLOCK = /<([a-z_]+)((?:\s+[a-z_]+="[^"]*")*)>\n([\s\S]*?)\n<\/\1>/g;

function attrs(raw: string): Record<string, string> {
	return Object.fromEntries([...raw.matchAll(/([a-z_]+)="([^"]*)"/g)].map((m) => [m[1], m[2]]));
}

function humanise(tag: string): string {
	const s = tag.replaceAll('_', ' ');
	return s.charAt(0).toUpperCase() + s.slice(1);
}

/** The message sent with a call: meeting details, evidence, guidance, earlier outputs, task. */
export function parseMessage(message: string): PromptSection[] {
	const sections: PromptSection[] = [];
	let i = 0;
	for (const m of message.matchAll(BLOCK)) {
		const [, tag, rawAttrs, text] = m;
		const key = `${tag}-${i++}`;
		if (tag in EVIDENCE_TAGS) {
			const a = attrs(rawAttrs);
			sections.push({
				key,
				kind: 'evidence',
				title: EVIDENCE_TAGS[tag],
				detail: [a.source_id, a.filename].filter(Boolean).join(' · '),
				text
			});
		} else {
			const known = TAGS[tag];
			sections.push({ key, kind: known?.kind ?? 'earlier', title: known?.title ?? humanise(tag), text });
		}
	}
	return sections.length ? sections : [{ key: 'message', kind: 'task', title: 'Message', text: message }];
}

/** The instructions: the role preamble, then each top-level "# " heading. */
export function parseSystem(system: string): PromptSection[] {
	const parts = system.split(/\n(?=# )/);
	return parts.map((text, i) => {
		const heading = text.startsWith('# ') ? text.slice(2, text.indexOf('\n') > 0 ? text.indexOf('\n') : undefined) : null;
		return {
			key: `system-${i}`,
			kind: 'instructions' as const,
			title: heading ?? 'Role and ground rules',
			text: heading ? text.slice(text.indexOf('\n') + 1).trim() : text.trim()
		};
	});
}

/** Rough token estimate for display (about 4 characters per token). */
export function approxTokens(text: string): string {
	const n = Math.round(text.length / 4);
	return n >= 1000 ? `~${(n / 1000).toFixed(1)}k tokens` : `~${n} tokens`;
}
