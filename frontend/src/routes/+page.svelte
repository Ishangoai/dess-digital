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

  let files = $state<FileList | null>(null);
  let statusMessage = $state<string>("");
  let isUploading = $state<boolean>(false);
  let isError = $state<boolean>(false);

  let jobs = $state<Job[]>([]);
  let isLoadingJobs = $state<boolean>(true);
  let jobsError = $state<string>("");

  async function loadJobs() {
    try {
      const response = await fetch("/api/jobs/");

      if (!response.ok) {
        throw new Error("Failed to retrieve jobs.");
      }

      jobs = await response.json();
      jobsError = "";
    } catch (err: unknown) {
      jobsError =
        err instanceof Error ? err.message : "An unexpected error occurred.";
    } finally {
      isLoadingJobs = false;
    }
  }

  function formatDate(value: string | null): string {
    if (!value) {
      return "—";
    }

    return new Date(value).toLocaleString();
  }

  onMount(() => {
    loadJobs();

    const interval = window.setInterval(loadJobs, 5000);

    return () => {
      window.clearInterval(interval);
    };
  });

  async function uploadFile() {
    if (!files || files.length === 0) {
      statusMessage = "Please select a file first.";
      isError = true;
      return;
    }

    const selectedFile = files[0];
    const formData = new FormData();
    formData.append("file", selectedFile);

    isUploading = true;
    statusMessage = "Uploading...";
    isError = false;

    try {
      const response = await fetch("/api/files/upload", {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || "Upload failed");
      }

      statusMessage = `Uploaded successfully! Saved to: ${result.timestamp_folder}/${result.filename}`;
      isError = false;
      files = null;
    } catch (err: unknown) {
      statusMessage = `Error: ${
        err instanceof Error ? err.message : "An unexpected error occurred."
      }`;
      isError = true;
    } finally {
      isUploading = false;
    }
  }
</script>

<main class="container">
  <h1>dess-digital</h1>
  <p class="subtitle">Document Ingestion & Processing</p>

  <section class="card">
    <h2>Upload Document</h2>

    <label for="file-input">Select Document</label>
    <input
      id="file-input"
      type="file"
      bind:files
      accept=".doc,.docx,.pdf,.txt"
      disabled={isUploading}
    />

    <button
      onclick={uploadFile}
      disabled={isUploading || !files || files.length === 0}
    >
      {isUploading ? "Uploading..." : "Upload File"}
    </button>

    {#if statusMessage}
      <p class="status" class:error={isError}>
        {statusMessage}
      </p>
    {/if}
  </section>

  <section class="jobs-section">
    <div class="jobs-heading">
      <h2>Background Jobs</h2>
      <button class="refresh-button" onclick={loadJobs}> Refresh </button>
    </div>

    {#if isLoadingJobs}
      <p>Loading jobs...</p>
    {:else if jobsError}
      <p class="status error">{jobsError}</p>
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
              <p class="status error">Error: {job.error_message}</p>
            {/if}
          </article>
        {/each}
      </div>
    {/if}
  </section>
</main>

<style>
  .container {
    font-family:
      system-ui,
      -apple-system,
      sans-serif;
    max-width: 720px;
    margin: 60px auto;
    padding: 0 16px;
  }

  h1 {
    margin-bottom: 4px;
    font-size: 1.75rem;
  }

  h2 {
    margin: 0;
    font-size: 1.2rem;
  }

  .subtitle {
    color: #666;
    margin-top: 0;
    margin-bottom: 24px;
    font-size: 0.95rem;
  }

  .card,
  .job-card {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 24px;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  label {
    font-weight: 600;
    font-size: 0.9rem;
  }

  input[type="file"] {
    border: 1px dashed #cbd5e1;
    padding: 12px;
    border-radius: 6px;
    cursor: pointer;
  }

  button {
    padding: 10px 16px;
    background-color: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-weight: 500;
    font-size: 0.95rem;
  }

  button:hover:not(:disabled) {
    background-color: #1d4ed8;
  }

  button:disabled {
    background-color: #93c5fd;
    cursor: not-allowed;
  }

  .status {
    margin: 0;
    font-size: 0.875rem;
    color: #16a34a;
    word-break: break-all;
  }

  .status.error {
    color: #dc2626;
  }

  .jobs-section {
    margin-top: 36px;
  }

  .jobs-heading,
  .job-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
  }

  .jobs-heading {
    margin-bottom: 16px;
  }

  .refresh-button {
    padding: 7px 12px;
  }

  .empty-message {
    color: #64748b;
    padding: 20px 0;
  }

  .jobs-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .job-card {
    padding: 18px;
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
    padding: 4px 9px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .pending {
    background: #fef3c7;
    color: #92400e;
  }

  .running {
    background: #dbeafe;
    color: #1e40af;
  }

  .completed {
    background: #dcfce7;
    color: #166534;
  }

  .failed {
    background: #fee2e2;
    color: #991b1b;
  }

  dl {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 14px;
    margin-bottom: 0;
  }

  dt {
    color: #64748b;
    font-size: 0.8rem;
  }

  dd {
    margin: 4px 0 0;
    font-size: 0.85rem;
  }
</style>
