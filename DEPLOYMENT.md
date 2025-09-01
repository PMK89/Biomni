# Biomni Deployment Guide (Local + Azure)

This guide walks you through:

- Local Docker test on your computer (with and without subpath)
- Azure VM provisioning and data mounting (managed disk or Blobfuse2)
- Building/pushing the image to Azure Container Registry (ACR)
- Production deployment with Nginx + TLS
- Optional subpath deployment under an existing domain (e.g., https://ai.esqlabs.com/biomni)

Key files referenced:
- `deploy/docker-compose.yml` (base compose)
- `deploy/docker-compose.prod.yml` (production compose)
- `deploy/docker-compose.local.yml` (local-only overrides)
- `deploy/nginx.conf` (TLS-terminating Nginx for standalone domain)
- `deploy/.env.example` (env template)

The app honors an optional `ROOT_PATH` (via Uvicorn `--root-path`) for subpath deployments.

---

## 1) Prerequisites

- Docker Desktop or Docker CE with Compose plugin
- Azure CLI (`az`) if deploying to Azure
- Domain name (only for standalone-domain deployment)

---

## 2) Local Docker Test (recommended)

This proves the container builds/starts and the app runs before touching Azure.

1. Create a local env file from the example:
   
   ```bash
   cp deploy/.env.example deploy/.env.local
   # Edit deploy/.env.local as needed
   # For local login via Azure Entra, add:
   #  - Redirect URI: http://localhost:8000/getAToken
   #  - Post-logout redirect: http://localhost:8000/
   ```

2. Prepare a local data folder (persist uploads, etc.):
   
   ```bash
   mkdir -p local_data/uploads local_data/user_dbs
   ```

3. Start locally (build + run):
   
   ```bash
   docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml up --build
   ```

   - App will be available at: http://localhost:8000/
   - Gradio: http://localhost:8000/gradio

### Local environment (.env) and data paths

The local override compose `deploy/docker-compose.local.yml` mounts your repo root `.env` into the container at `/app/.env` by default:

```yaml
volumes:
  - ${ENV_FILE_PATH:-../.env}:/app/.env:ro
  - ${LOCAL_DATA_PATH:-../local_data}:/mnt/biomni_data
```

- You can point to a different env file by exporting `ENV_FILE_PATH` before `docker compose up`.
- Local data is expected under `./local_data` on the host. It is mounted into the container at `/mnt/biomni_data`.
- The web app stores uploads at `BIOMNI_BASE_PATH/uploads`. With defaults, this resolves to `./local_data/uploads` on your machine.
- The agent uses `default_config.path` (from `biomni/config.py`), which defaults to `./local_data`. You can override via `BIOMNI_PATH` in your `.env`.
- Startup downloads can be controlled via environment variables (read by `biomni/agent/a1.py`):
  - `BIOMNI_SKIP_DOWNLOADS` (true/false) to skip S3 bootstrap
  - `BIOMNI_DOWNLOAD_TIMEOUT` (seconds, float allowed)
  - `BIOMNI_S3_BASE_URL` (override S3 base URL)

4. Optional: Test subpath locally (e.g., `/biomni`):
   
   ```bash
   # Run with ROOT_PATH set
   ROOT_PATH=/biomni \
   docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml up --build
   
   # Use these local redirect URIs in Azure Entra App Registration:
   #   http://localhost:8000/biomni/getAToken (redirect)
   #   http://localhost:8000/biomni/          (post-logout)
   ```
   
   - App: http://localhost:8000/biomni/
   - Gradio: http://localhost:8000/biomni/gradio

5. Stop local stack:
   
   ```bash
   docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml down -v
   ```

---

## 3) Azure Entra (Microsoft Entra) App Registration

Create/update an App Registration and capture:
- `CLIENT_ID`
- `CLIENT_SECRET`
- `TENANT_ID`

Add redirect URIs based on your deployment mode:

- Local root: `http://localhost:8000/getAToken`
- Local subpath: `http://localhost:8000/biomni/getAToken`
- Standalone prod domain: `https://your.domain.tld/getAToken`
- Subpath under existing domain: `https://ai.esqlabs.com/biomni/getAToken`

Set post-logout redirect to the corresponding base path:
- `http://localhost:8000/` or `http://localhost:8000/biomni/`
- `https://your.domain.tld/` or `https://ai.esqlabs.com/biomni/`

---

## 4) Build & Push Image to ACR (off-VM recommended)

1. Create ACR (once):
   
   ```bash
   ACR_NAME=myacrname   # globally unique
   az acr create -g <resource-group> -n $ACR_NAME --sku Basic
   az acr login -n $ACR_NAME
   ```

2. Build and push:
   
   ```bash
   IMAGE_TAG=${ACR_NAME}.azurecr.io/biomni:latest
   docker build -t $IMAGE_TAG .
   docker push $IMAGE_TAG
   ```

3. On the VM, set `APP_IMAGE=$IMAGE_TAG` when starting compose.

---

## 5) Provision the Azure VM

Example (Ubuntu 22.04 LTS, change sizes and networking to your needs):

```bash
RG=my-rg
LOC=westeurope
VM_NAME=biomni-vm

az group create -n $RG -l $LOC
az vm create \
  -g $RG -n $VM_NAME \
  --image Ubuntu2204 \
  --size Standard_B2ms \
  --admin-username azureuser \
  --generate-ssh-keys

# Open ports if using standalone Nginx on VM (80/443)
az vm open-port -g $RG -n $VM_NAME --port 80 --priority 1001
az vm open-port -g $RG -n $VM_NAME --port 443 --priority 1002

# If exposing the app directly (not recommended), open 8000 to trusted IPs only
# Prefer keeping 8000 locked down or private.
```

SSH in:

```bash
az vm show -d -g $RG -n $VM_NAME --query publicIps -o tsv
ssh azureuser@<VM_PUBLIC_IP>
```

Install Docker (VM):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out/in to refresh group or run: newgrp docker

# Compose plugin (Ubuntu):
sudo apt-get update && sudo apt-get install -y docker-compose-plugin
```

Clone the repo or upload only the `deploy/` folder to the VM:

```bash
mkdir -p ~/biomni && cd ~/biomni
# Option A: copy deploy/ folder via scp
# scp -r deploy azureuser@<VM_PUBLIC_IP>:~/biomni/
# Option B: git clone full repo
# git clone <your_repo_url> .
```

---

## 6) Data Lake: Mounting Options on the VM

Choose one (recommended: managed disk). Ensure the mount point is `/mnt/biomni_data` to match compose.

### Option A: Managed Data Disk (recommended)

Attach a new disk (e.g., 64GB):

```bash
DISK_NAME=biomni-data-disk
az disk create -g $RG -n $DISK_NAME --size-gb 64 --sku StandardSSD_LRS
az vm disk attach -g $RG --vm-name $VM_NAME --name $DISK_NAME
```

On the VM, find the device (e.g., `/dev/sdc`), partition/format/mount:

```bash
lsblk
sudo parted /dev/sdc --script mklabel gpt mkpart primary ext4 0% 100%
sudo mkfs.ext4 -F /dev/sdc1
sudo mkdir -p /mnt/biomni_data
sudo blkid /dev/sdc1  # copy the UUID

# Add to /etc/fstab (replace with your UUID):
echo 'UUID=<YOUR-UUID> /mnt/biomni_data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
ls -la /mnt/biomni_data
```

Copy your 12GB data into `/mnt/biomni_data`.

### Option B: Azure Blob Storage with blobfuse2

```bash
# Install blobfuse2
curl -sSL https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb -o packages-microsoft-prod.deb
sudo dpkg -i packages-microsoft-prod.deb
sudo apt-get update && sudo apt-get install -y blobfuse2

# Create a config
mkdir -p ~/.config/blobfuse2
cat > ~/.config/blobfuse2/biomni.yaml <<'YAML'
logging:
  type: syslog
components:
  - libblobfuse
  - attr_cache
  - file_cache
  - fuse
libblobfuse:
  account-name: <STORAGE_ACCOUNT>
  account-key: <ACCOUNT_KEY>
  container: <CONTAINER_NAME>
file_cache:
  path: /mnt/blobfuse_cache
  timeout-sec: 120
YAML

sudo mkdir -p /mnt/biomni_data /mnt/blobfuse_cache
sudo chown $USER:$USER /mnt/biomni_data /mnt/blobfuse_cache

# Mount
blobfuse2 mount /mnt/biomni_data --config-file ~/.config/blobfuse2/biomni.yaml -f &
```

Upload data via `azcopy` to the container.

---

## 7) Production Environment File on VM

Create `/opt/biomni/.env` (or choose another path and set `ENV_FILE_PATH` when running compose):

```bash
sudo mkdir -p /opt/biomni
sudo tee /opt/biomni/.env >/dev/null <<'ENV'
# Session cookie secret
SESSION_SECRET=replace_with_random_string

# Azure Entra App (use your IDs and secrets)
CLIENT_ID=00000000-0000-0000-0000-000000000000
CLIENT_SECRET=replace_with_client_secret
TENANT_ID=00000000-0000-0000-0000-000000000000

# Optional OpenAI/Azure OpenAI
OPENAI_API_KEY=
OPENAI_API_BASE=
OPENAI_ENDPOINT=
OPENAI_API_TYPE=azure

# Data paths
BIOMNI_BASE_PATH=/mnt/biomni_data
USER_DB_DIR=/mnt/biomni_data/user_dbs
ENV
```

---

## 8) Standalone Domain Deployment (VM handles HTTPS)

Use the provided Nginx + certbot stack on the VM.

1. Edit `deploy/nginx.conf` and set your domain:
   - Replace `your.domain.tld` in both `server_name` and certificate paths.

2. Issue certificate and start Nginx:
   
   ```bash
   cd ~/biomni/deploy
   docker compose -f docker-compose.yml up -d nginx
   docker compose -f docker-compose.yml run --rm certbot \
     certbot certonly --webroot -w /var/www/certbot \
     -d your.domain.tld --email you@example.com --agree-tos --no-eff-email
   docker compose -f docker-compose.yml restart nginx
   ```

3. Start the app with the prebuilt image and mounted data/env:
   
   ```bash
   export APP_IMAGE=<acr>.azurecr.io/biomni:latest
   docker compose -f docker-compose.prod.yml up -d
   ```

4. Azure Entra redirect URIs:
   - `https://your.domain.tld/getAToken`
   - Post-logout: `https://your.domain.tld/`

5. Test:
   - Open `https://your.domain.tld/` → Login → Azure → back to `/getAToken` → `/` → `/gradio`.
   - Upload a file → persists at `/mnt/biomni_data/uploads`.

---

## 9) Optional: Subpath Deployment under an existing domain

If ESQ AI already runs at `https://ai.esqlabs.com/`, you can publish Biomni at `https://ai.esqlabs.com/biomni` without a new domain.

- On the Biomni VM: do NOT expose ports publicly. Run Biomni with `ROOT_PATH=/biomni` and restrict port 8000 to only the ESQ AI VM (via NSG allow-list).
- On the ESQ AI Nginx: add a `/biomni/` location that proxies to the Biomni VM.

1. Start Biomni on its VM (no TLS, private 8000):
   
   ```bash
   export APP_IMAGE=<acr>.azurecr.io/biomni:latest
   export ROOT_PATH=/biomni
   docker compose -f deploy/docker-compose.prod.yml up -d
   ```

2. On the ESQ AI Nginx host (public), add a block:
   
   ```nginx
   # In your existing HTTPS server for ai.esqlabs.com
   location /biomni/ {
       proxy_pass http://<OMNI_VM_IP>:8000;

       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;

       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";

       client_max_body_size 200M;
       proxy_connect_timeout 60s;
       proxy_send_timeout 3600s;
       proxy_read_timeout 3600s;

       proxy_buffering off;
       proxy_request_buffering off;
   }
   ```

   Reload Nginx after changes.

3. Azure Entra redirects for subpath:
   - `https://ai.esqlabs.com/biomni/getAToken`
   - Post-logout: `https://ai.esqlabs.com/biomni/`

4. Test:
   - Open `https://ai.esqlabs.com/biomni/` → Login flow → `/biomni/gradio`.

---

## 10) Operations

- Logs:
  - `docker compose -f deploy/docker-compose.prod.yml logs -f biomni-app`
  - `docker compose -f deploy/docker-compose.yml logs -f nginx`
- Restart:
  - `docker compose -f deploy/docker-compose.prod.yml restart biomni-app`
- Update image:
  - Push a new `:latest` to ACR, SSH to VM:
    ```bash
    export APP_IMAGE=<acr>.azurecr.io/biomni:latest
    docker compose -f deploy/docker-compose.prod.yml pull
    docker compose -f deploy/docker-compose.prod.yml up -d
    ```

---

## 11) Checklist

- [ ] Local container builds and starts
- [ ] Azure Entra redirect URIs set (local + prod)
- [ ] Data lake available at `/mnt/biomni_data`
- [ ] `.env` created on VM with secrets and data paths
- [ ] APP_IMAGE set to ACR image on VM
- [ ] Standalone: TLS cert issued, Nginx running
- [ ] Subpath: ESQ AI Nginx proxies `/biomni/` to Biomni VM; `ROOT_PATH=/biomni`
- [ ] E2E tested: login, `/gradio`, uploads persist
