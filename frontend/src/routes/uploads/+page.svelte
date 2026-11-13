<script lang="ts">
    import { onMount } from "svelte";

    interface Job {
        id: string;
        function_name: string;
        function_params: Record<string, unknown>;
        status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
        created_at: string;
        started_at: string | null;
        completed_at: string | null;
        error_message: string | null;
    }

    let jobs = $state<Job[]>([]);
    let isLoadingJobs = $state(true);
    let jobsError = $state("");

    async function loadJobs() {
        try {
            const response = await fetch("/api/jobs/");

            if (!response.ok) {
                throw new Error("Failed to retrieve jobs.");
            }

            jobs = await response.json();
            jobsError = "";
        } catch (err: unknown) {
            jobsError = err instanceof Error ? err.message : "An unexpected error occurred.";
        } finally {
            isLoadingJobs = false;
        }
    }

    function formatDate(value: string | null): string {
        return value ? new Date(value).toLocaleString() : "-";
    }

    onMount(() => {
        loadJobs();
        const interval = window.setInterval(loadJobs, 5000);
        return () => window.clearInterval(interval);
    });

    let files = $state({
        agenda: null as FileList | null,
        transcript: null as FileList | null,
        meeting_notes: null as FileList | null
    });

    let uploadStatus = $state("");
    let errorMessage = $state("");
    let isUploading = $state(false);

    async function handleUpload(event: Event) {
        event.preventDefault();
        isUploading = true;
        uploadStatus = "";
        errorMessage = "";

        if (!files.agenda?.[0]) {
            errorMessage = "Agenda is required.";
            isUploading = false;
            return;
        }

        if (!files.transcript?.[0] && !files.meeting_notes?.[0]) {
            errorMessage = "You must upload either a transcript or meeting notes (or both) alongside the agenda.";
            isUploading = false;
            return;
        }

        const formData = new FormData();
        formData.append("agenda", files.agenda[0]);
        
        if (files.transcript?.[0]) {
            formData.append("transcript", files.transcript[0]);
        }
        if (files.meeting_notes?.[0]) {
            formData.append("meeting_notes", files.meeting_notes[0]);
        }

        try {
            const response = await fetch("/api/files/upload", {
                method: "POST",
                body: formData
            });

            const result = await response.json();

            if (response.ok) {
                uploadStatus = "Files uploaded successfully!";
                files = { agenda: null, transcript: null, meeting_notes: null };
                (event.target as HTMLFormElement).reset();
            } else {
                errorMessage = result.detail || "An error occurred during upload.";
            }
        } catch (error) {
            errorMessage = "Network error. Please try again.";
        } finally {
            isUploading = false;
        }
    }
</script>

<main class="page-wrapper">
    <!-- New Brand Header -->
    <header class="app-header">
        <h1>File uploads</h1>
    </header>

    <div class="upload-card">
        <div class="card-header">
            <div class="icon-wrapper">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
            </div>
            <!-- Changed to h2 to maintain correct HTML semantics -->
            <h2>Upload Documents</h2>
            <p class="subtitle">Securely upload your meeting files to the workspace.</p>
        </div>
        
        <form onsubmit={handleUpload} class="upload-form">
            
            <!-- Agenda (Required) -->
            <div class="form-group required">
                <label for="agenda">Meeting Agenda</label>
                <div class="input-wrapper">
                    <input 
                        type="file" 
                        id="agenda" 
                        bind:files={files.agenda} 
                        accept="application/pdf,.doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        required
                    />
                </div>
                <small class="helper-text">PDF or MS Word format (.pdf, .doc, .docx)</small>
            </div>

            <div class="divider">
                <span>Optional Files</span>
            </div>

            <!-- Transcript (Optional) -->
            <div class="form-group">
                <label for="transcript">Meeting Transcript</label>
                <div class="input-wrapper">
                    <input 
                        type="file" 
                        id="transcript" 
                        bind:files={files.transcript} 
                        accept="application/pdf,.doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    />
                </div>
                <small class="helper-text">PDF or MS Word format (.pdf, .doc, .docx)</small>
            </div>

            <!-- Meeting Notes (Optional) -->
            <div class="form-group">
                <label for="meeting_notes">Meeting Notes</label>
                <div class="input-wrapper">
                    <input 
                        type="file" 
                        id="meeting_notes" 
                        bind:files={files.meeting_notes} 
                        accept="application/pdf,.doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    />
                </div>
                <small class="helper-text">PDF or MS Word format (.pdf, .doc, .docx)</small>
            </div>

            <button type="submit" disabled={isUploading} class:loading={isUploading}>
                {isUploading ? 'Uploading...' : 'Upload Files'}
            </button>
        </form>

        {#if uploadStatus}
            <div class="alert success" role="alert">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                {uploadStatus}
            </div>
        {/if}
        
        {#if errorMessage}
            <div class="alert error" role="alert">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                {errorMessage}
            </div>
        {/if}
    </div>

    <section class="jobs-section">
        <div class="jobs-heading">
            <h2>Background Jobs</h2>
            <button class="refresh-button" onclick={loadJobs}>Refresh</button>
        </div>

        {#if isLoadingJobs}
            <p>Loading jobs...</p>
        {:else if jobsError}
            <p class="jobs-error">{jobsError}</p>
        {:else if jobs.length === 0}
            <p class="empty-message">No jobs have been submitted yet.</p>
        {:else}
            <div class="jobs-list">
                {#each jobs as job (job.id)}
                    <article class="job-card">
                        <div class="job-heading">
                            <h3>{job.function_name}</h3>
                            <span
                                class="job-status"
                                class:pending={job.status === "PENDING"}
                                class:running={job.status === "RUNNING"}
                                class:completed={job.status === "COMPLETED"}
                                class:failed={job.status === "FAILED"}
                            >
                                {job.status}
                            </span>
                        </div>

                        <p class="job-id">ID: {job.id}</p>

                        <dl>
                            <div>
                                <dt>Created</dt>
                                <dd>{formatDate(job.created_at)}</dd>
                            </div>
                            <div>
                                <dt>Started</dt>
                                <dd>{formatDate(job.started_at)}</dd>
                            </div>
                            <div>
                                <dt>Completed</dt>
                                <dd>{formatDate(job.completed_at)}</dd>
                            </div>
                        </dl>

                        {#if job.error_message}
                            <p class="jobs-error">Error: {job.error_message}</p>
                        {/if}
                    </article>
                {/each}
            </div>
        {/if}
    </section>
</main>

<style>
    .page-wrapper {
        display: flex;
        flex-direction: column; /* Stack header and card vertically */
        justify-content: center;
        align-items: center;
        padding: 2rem;
    }

    /* App Brand Header */
    .app-header {
        margin-bottom: 2rem;
        text-align: center;
    }

    .app-header h1 {
        margin: 0;
        font-size: 2.25rem;
        font-weight: 700;
        color: #0f172a;
        letter-spacing: -0.025em;
    }

    /* Card styling */
    .upload-card {
        background: #ffffff;
        width: 100%;
        max-width: 520px;
        border-radius: 16px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 10px 15px -3px rgba(0, 0, 0, 0.02);
        padding: 2.5rem;
        border: 1px solid #e2e8f0;
    }

    /* Card Header */
    .card-header {
        text-align: center;
        margin-bottom: 2rem;
    }

    .icon-wrapper {
        background-color: #eff6ff;
        color: #3b82f6;
        width: 48px;
        height: 48px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 1rem;
    }

    .card-header h2 {
        margin: 0 0 0.5rem 0;
        font-size: 1.5rem;
        font-weight: 600;
        color: #1e293b;
    }

    .subtitle {
        margin: 0;
        color: #64748b;
        font-size: 0.9rem;
    }

    /* Form Layout */
    .upload-form {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
    }

    label {
        font-size: 0.9rem;
        font-weight: 500;
        color: #334155;
    }

    .required label::after {
        content: "*";
        color: #ef4444;
        margin-left: 0.25rem;
    }

    /* Custom File Input Styling */
    .input-wrapper {
        border: 2px dashed #cbd5e1;
        border-radius: 8px;
        padding: 0.5rem;
        background-color: #f8fafc;
        transition: all 0.2s ease;
    }

    .input-wrapper:hover {
        border-color: #94a3b8;
        background-color: #f1f5f9;
    }

    input[type="file"] {
        width: 100%;
        font-size: 0.85rem;
        color: #64748b;
        cursor: pointer;
    }

    input[type="file"]::file-selector-button {
        background-color: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-right: 1rem;
        color: #334155;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }

    input[type="file"]::file-selector-button:hover {
        background-color: #f1f5f9;
        border-color: #94a3b8;
    }

    .helper-text {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-left: 0.25rem;
    }

    /* Divider */
    .divider {
        display: flex;
        align-items: center;
        text-align: center;
        margin: 0.5rem 0;
    }
    
    .divider::before,
    .divider::after {
        content: '';
        flex: 1;
        border-bottom: 1px solid #e2e8f0;
    }
    
    .divider span {
        padding: 0 10px;
        color: #94a3b8;
        font-size: 0.8rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Submit Button */
    button {
        margin-top: 1rem;
        padding: 0.875rem;
        background-color: #3b82f6;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        font-weight: 500;
        cursor: pointer;
        transition: background-color 0.2s ease, transform 0.1s ease;
        box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);
    }

    button:hover:not(:disabled) {
        background-color: #2563eb;
    }

    button:active:not(:disabled) {
        transform: translateY(1px);
    }

    button:disabled {
        background-color: #94a3b8;
        cursor: not-allowed;
        box-shadow: none;
    }

    button.loading {
        opacity: 0.8;
    }

    /* Alerts */
    .alert {
        margin-top: 1.5rem;
        padding: 1rem;
        border-radius: 8px;
        font-size: 0.9rem;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        font-weight: 500;
        animation: slideIn 0.3s ease-out;
    }

    .alert.success {
        background-color: #ecfdf5;
        color: #065f46;
        border: 1px solid #a7f3d0;
    }

    .alert.error {
        background-color: #fef2f2;
        color: #991b1b;
        border: 1px solid #fecaca;
    }

    @keyframes slideIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Background Jobs */
    .jobs-section {
        width: 100%;
        max-width: 520px;
        margin-top: 2.5rem;
    }

    .jobs-heading,
    .job-heading {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
    }

    .jobs-heading {
        margin-bottom: 1rem;
    }

    .jobs-heading h2 {
        margin: 0;
        font-size: 1.25rem;
        font-weight: 600;
        color: #1e293b;
    }

    .refresh-button {
        margin-top: 0;
        padding: 0.45rem 0.9rem;
        font-size: 0.85rem;
    }

    .empty-message {
        color: #64748b;
        padding: 1.25rem 0;
    }

    .jobs-error {
        color: #991b1b;
        font-size: 0.875rem;
    }

    .jobs-list {
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    .job-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }

    .job-card h3 {
        margin: 0;
        font-size: 1rem;
    }

    .job-id {
        color: #64748b;
        font-size: 0.8rem;
        overflow-wrap: anywhere;
    }

    .job-status {
        padding: 0.25rem 0.6rem;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .pending { background: #fef3c7; color: #92400e; }
    .running { background: #dbeafe; color: #1e40af; }
    .completed { background: #dcfce7; color: #166534; }
    .failed { background: #fee2e2; color: #991b1b; }

    dl {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 0.9rem;
        margin-bottom: 0;
    }

    dt {
        color: #64748b;
        font-size: 0.8rem;
    }

    dd {
        margin: 0.25rem 0 0;
        font-size: 0.85rem;
    }
</style>