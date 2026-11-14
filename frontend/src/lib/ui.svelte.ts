// Small UI preferences shared across components, remembered per browser.

function stored(key: string, fallback: boolean): boolean {
	try {
		const v = localStorage.getItem(key);
		return v === null ? fallback : v === '1';
	} catch {
		return fallback;
	}
}

function save(key: string, value: boolean): void {
	try {
		localStorage.setItem(key, value ? '1' : '0');
	} catch {
		// storage unavailable (private mode); keep the in-memory value
	}
}

class UiState {
	sidebarCollapsed = $state(typeof window !== 'undefined' && stored('dess.sidebarCollapsed', false));
	aiPanelOpen = $state(typeof window !== 'undefined' && stored('dess.aiPanelOpen', false));

	toggleSidebar = () => {
		this.sidebarCollapsed = !this.sidebarCollapsed;
		save('dess.sidebarCollapsed', this.sidebarCollapsed);
	};

	setAiPanel = (open: boolean) => {
		this.aiPanelOpen = open;
		save('dess.aiPanelOpen', open);
	};
}

export const ui = new UiState();
