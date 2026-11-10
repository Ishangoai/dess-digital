<script lang="ts">
  let files = $state<FileList | null>(null);
  let statusMessage = $state<string>('');
  let isUploading = $state<boolean>(false);
  let isError = $state<boolean>(false);

  async function uploadFile() {
    if (!files || files.length === 0) {
      statusMessage = 'Please select a file first.';
      isError = true;
      return;
    }

    const selectedFile = files[0];
    const formData = new FormData();
    formData.append('file', selectedFile);

    isUploading = true;
    statusMessage = 'Uploading...';
    isError = false;

    try {
      const response = await fetch('/api/files/upload', {
        method: 'POST',
        body: formData
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || 'Upload failed');
      }

      statusMessage = `Uploaded successfully! Saved to: ${result.timestamp_folder}/${result.filename}`;
      isError = false;
      files = null;
    } catch (err: any) {
      statusMessage = `Error: ${err.message}`;
      isError = true;
    } finally {
      isUploading = false;
    }
  }
</script>

<main class="container">
  <h1>dess-digital</h1>
  <p class="subtitle">Document Ingestion & Processing</p>

  <div class="card">
    <label for="file-input">Select Document</label>
    <input
      id="file-input"
      type="file"
      bind:files
      accept=".doc,.docx,.pdf,.txt"
      disabled={isUploading}
    />

    <button onclick={uploadFile} disabled={isUploading || !files || files.length === 0}>
      {isUploading ? 'Uploading...' : 'Upload File'}
    </button>

    {#if statusMessage}
      <p class="status" class:error={isError}>
        {statusMessage}
      </p>
    {/if}
  </div>
</main>

<style>
  .container {
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 480px;
    margin: 60px auto;
    padding: 0 16px;
  }

  h1 {
    margin-bottom: 4px;
    font-size: 1.75rem;
  }

  .subtitle {
    color: #666;
    margin-top: 0;
    margin-bottom: 24px;
    font-size: 0.95rem;
  }

  .card {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    background: #fff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  label {
    font-weight: 600;
    font-size: 0.9rem;
  }

  input[type='file'] {
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
    transition: background-color 0.2s;
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
</style>