# DESS prototype

Static clickable walkthrough of the app for the business demo: Steps 1 to 4, learning from edits, committee profile set-up. Synthetic meeting and companies, no AI, no backend.

Open locally: `open index.html`.

## Serve on the VM

No build or Caddyfile change. A compose override mounts this folder into the web container, and the deploy's `docker compose up -d` keeps picking it up.

```bash
# your machine, from this folder
gcloud compute scp index.html docker-compose.override.yml dess-digital:/tmp/ --zone europe-west2-a --tunnel-through-iap
gcloud compute ssh dess-digital --zone europe-west2-a --tunnel-through-iap

# on the VM
sudo docker compose ls        # CONFIG FILES = the deployed docker-compose.yml
DIR=/path/from/above          # its folder (the deploy user's home, not yours)
sudo mkdir -p $DIR/prototype
sudo mv /tmp/index.html $DIR/prototype/
sudo mv /tmp/docker-compose.override.yml $DIR/
cd $DIR && sudo docker compose up -d web
```

URL: `https://dess.cloud-apps.ishango.ai/prototype/index.html` (the `/index.html` is needed; `/prototype/` falls through to the app).

Update: replace `$DIR/prototype/index.html`. No restart.

## Take offline

```bash
cd $DIR && sudo rm -r prototype docker-compose.override.yml && sudo docker compose up -d web
```
