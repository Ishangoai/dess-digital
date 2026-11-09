<script lang="ts">
    import { onMount } from 'svelte';

    // Describes the structure of one job returned by FastAPI.
    type Job = {
        id: string;
        function_name: string;
        status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
        created_at: string;
        started_at: string | null;
        completed_at: string | null;
        error_message: string | null;
    };

    // Describes the response returned by GET /api/jobs/.
    type JobListResponse = {
        jobs: Job[];
        total: number;
    };

    let jobs: Job[] = $state([]);
    let total = $state(0);
    let loading = $state(true);
    let error = $state<string | null>(null);

    async function fetchJobs() {
        loading = true;
        error = null;

        try {
            const response = await fetch('/api/jobs/');

            if (!response.ok) {
                throw new Error(`Failed to retrieve jobs: ${response.status}`);
            }

            const data: JobListResponse = await response.json();

            jobs = data.jobs;
            total = data.total;
        } catch (err) {
            error = err instanceof Error
                ? err.message
                : 'An unexpected error occurred.';
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        fetchJobs();
    });
</script>

<svelte:head>
    <title>Jobs | DESS Digital</title>
</svelte:head>

<main>
    <header>
        <div>
            <h1>Background Jobs</h1>
            <p>Monitor document processing tasks.</p>
        </div>

        <button onclick={fetchJobs} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
        </button>
    </header>

    <section>
        <h2>All Jobs ({total})</h2>

        {#if loading}
            <p>Loading jobs...</p>

        {:else if error}
            <p role="alert">{error}</p>

        {:else if jobs.length === 0}
            <p>No jobs found.</p>

        {:else}
            <table>
                <thead>
                    <tr>
                        <th>Function</th>
                        <th>Status</th>
                        <th>Created</th>
                    </tr>
                </thead>

                <tbody>
                    {#each jobs as job (job.id)}
                        <tr>
                            <td>{job.function_name}</td>
                            <td>{job.status}</td>
                            <td>
                                {new Date(job.created_at).toLocaleString()}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    </section>
</main>

<style>
    main {
        max-width: 1100px;
        margin: 40px auto;
        padding: 0 24px;
    }

    header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        margin-bottom: 32px;
    }

    button {
        padding: 10px 16px;
        cursor: pointer;
    }

    button:disabled {
        cursor: not-allowed;
        opacity: 0.6;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        text-align: left;
    }

    th,
    td {
        padding: 12px;
        border-bottom: 1px solid #ddd;
    }
</style>
