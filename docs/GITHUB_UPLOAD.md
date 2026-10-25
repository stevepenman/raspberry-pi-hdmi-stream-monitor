# Upload this prepared folder to your personal GitHub

The portfolio folder is already a fresh local Git repository on branch `main`, with no commits or remote. Do not run these commands in the original project folder. Do not copy its history or upload the entire workspace.

Before publishing, complete [the publication review](PUBLICATION_REVIEW.md), including permission to disclose the code. No project licence has been added.

## 1. Open the correct folder

Open `portfolio-raspberry-pi-hdmi-stream-monitor` in File Explorer, right-click inside it and choose **Open in Terminal** (PowerShell). If your terminal starts elsewhere, use `Set-Location` with the actual path to that portfolio folder.

Check:

```powershell
Get-Location
git status
git remote -v
```

The location must end in `portfolio-raspberry-pi-hdmi-stream-monitor`. Status should show a new repository on `main` with no commits. `git remote -v` should print nothing. The ignored `.venv` should not appear in the untracked files.

## 2. Verify and inspect what will be uploaded

The prepared local virtual environment is available on this computer:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B tools/smoke_demo.py
.\.venv\Scripts\python.exe -B tools/check_syntax.py
.\.venv\Scripts\python.exe -B tools/check_publication.py
.\.venv\Scripts\python.exe -m pip check
git add --all
git diff --cached --stat
git diff --cached
```

The smoke check starts a temporary local server, requests only loopback addresses and then stops it. If viewing the diff opens a pager, press **q** to exit. Inspect every added file, including the generated image separately. Credentials, `.env`, `.venv`, logs and recordings must not be in the staged list. If anything is unexpected, stop and remove it from staging with `git rm --cached -- PATH_TO_FILE`, then correct `.gitignore` as needed.

## 3. Set the author for this repository and commit

Replace the placeholders below. Use a name you want displayed publicly. For the email, copy your exact GitHub no-reply address from **GitHub Settings → Emails** if you prefer not to publish a personal contact address. These settings apply to this repository only.

```powershell
git config user.name "YOUR_PUBLIC_AUTHOR_NAME"
git config user.email "YOUR_GITHUB_NOREPLY_ADDRESS"
git commit -m "Prepare HDMI streaming portfolio demo"
```

Do not enter a password or token into Git configuration or source files.

## 4. Create an empty repository on GitHub

Sign in to your **personal** GitHub account. Select **New repository** and verify that the owner is your personal account. Use:

- Name: `raspberry-pi-hdmi-stream-monitor`
- Description: `Python HDMI-to-browser streamer for Raspberry Pi, with MJPEG/HLS modes, authentication, health checks and a hardware-free synthetic demo.`
- Visibility: public only once publication rights and the final contents are confirmed. You can start private while reviewing.
- Leave initialization options empty: **do not add a README, .gitignore or licence** on GitHub, since this folder already contains the prepared files.

Create the repository and copy its HTTPS URL. It should point to your personal account and the new repository.

## 5. Connect and upload

Replace `YOUR_USERNAME` below with your actual personal GitHub username:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/raspberry-pi-hdmi-stream-monitor.git
git remote -v
git push -u origin main
```

Verify the remote output before pushing. If Git says `origin` already exists, inspect it before changing anything; the prepared repository initially has none. Authenticate using Git's browser or credential-manager prompt. Do not put a token in the URL. If a push is rejected because the GitHub repository already contains commits, do not force-push; use an empty repository or resolve the history deliberately.

## 6. Review the published result

Check that GitHub displays the README and demo image, then open **Actions** to inspect all CI jobs. The workflow installs dependencies and performs tests; it does not deploy or contact equipment. Only describe CI as passing after the jobs actually succeed.

Add the topics in [PORTFOLIO.md](PORTFOLIO.md) using the repository's About settings. Link the public repository URL on your CV after review. The same file provides two implementation-based CV bullets to adapt to your actual contribution.

These steps follow [GitHub's official instructions for adding locally hosted code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github). Nothing has been uploaded automatically.
