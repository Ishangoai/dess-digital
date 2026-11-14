<script lang="ts" module>
	// Stroke icons on a 24px grid (Lucide-style paths).
	const PATHS = {
		plus: ['M5 12h14', 'M12 5v14'],
		x: ['M18 6 6 18', 'm6 6 12 12'],
		check: ['M20 6 9 17l-5-5'],
		file: [
			'M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z',
			'M14 2v4a2 2 0 0 0 2 2h4',
			'M16 13H8',
			'M16 17H8',
			'M10 9H8'
		],
		upload: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm17 8-5-5-5 5', 'M12 3v12'],
		download: ['M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4', 'm7 10 5 5 5-5', 'M12 15V3'],
		search: ['M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0', 'm21 21-4.3-4.3'],
		chevronDown: ['m6 9 6 6 6-6'],
		chevronRight: ['m9 18 6-6-6-6'],
		alert: ['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0', 'M12 8v4', 'M12 16h.01'],
		pencil: ['M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z'],
		trash: [
			'M3 6h18',
			'M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6',
			'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2'
		],
		menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
		message: ['M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'],
		book: ['M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20'],
		paperclip: [
			'm21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48'
		],
		refresh: [
			'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8',
			'M21 3v5h-5',
			'M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16',
			'M8 16H3v5'
		],
		map: ['M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z', 'M9 3v15', 'M15 6v15'],
		layers: ['m12 2 10 5-10 5L2 7z', 'm2 17 10 5 10-5', 'm2 12 10 5 10-5'],
		arrowLeft: ['m12 19-7-7 7-7', 'M19 12H5'],
		arrowRight: ['M5 12h14', 'm12 5 7 7-7 7'],
		shield: ['M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z', 'm9 12 2 2 4-4']
	} as const;
	export type IconName = keyof typeof PATHS;
</script>

<script lang="ts">
	let { name, size = 16 }: { name: IconName; size?: number } = $props();
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	{#each PATHS[name] as d (d)}<path {d} />{/each}
</svg>

<style>
	svg {
		flex-shrink: 0;
	}
</style>
