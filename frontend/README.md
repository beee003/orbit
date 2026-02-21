# Welcome to your Lovable project

## Project info

**URL**: https://lovable.dev/projects/REPLACE_WITH_PROJECT_ID

## How can I edit this code?

There are several ways of editing your application.

**Use Lovable**

Simply visit the [Lovable Project](https://lovable.dev/projects/REPLACE_WITH_PROJECT_ID) and start prompting.

Changes made via Lovable will be committed automatically to this repo.

**Use your preferred IDE**

If you want to work locally using your own IDE, you can clone this repo and push changes. Pushed changes will also be reflected in Lovable.

The only requirement is having Node.js & npm installed - [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating)

Follow these steps:

```sh
# Step 1: Clone the repository using the project's Git URL.
git clone <YOUR_GIT_URL>

# Step 2: Navigate to the project directory.
cd <YOUR_PROJECT_NAME>

# Step 3: Install the necessary dependencies.
npm i

# Step 4: Start the development server with auto-reloading and an instant preview.
npm run dev
```

**Edit a file directly in GitHub**

- Navigate to the desired file(s).
- Click the "Edit" button (pencil icon) at the top right of the file view.
- Make your changes and commit the changes.

**Use GitHub Codespaces**

- Navigate to the main page of your repository.
- Click on the "Code" button (green button) near the top right.
- Select the "Codespaces" tab.
- Click on "New codespace" to launch a new Codespace environment.
- Edit files directly within the Codespace and commit and push your changes once you're done.

## What technologies are used for this project?

This project is built with:

- Vite
- TypeScript
- React
- shadcn-ui
- Tailwind CSS

## How can I deploy this project?

Simply open [Lovable](https://lovable.dev/projects/REPLACE_WITH_PROJECT_ID) and click on Share -> Publish.

## Can I connect a custom domain to my Lovable project?

Yes, you can!

To connect a domain, navigate to Project > Settings > Domains and click Connect Domain.

Read more here: [Setting up a custom domain](https://docs.lovable.dev/features/custom-domain#custom-domain)

## Using your phone camera for local dev (iPhone)

Mobile browsers only allow camera access in a **secure context** (HTTPS or localhost). This project’s dev server is configured to run over **HTTPS in development** so you can open it on your phone and use the phone camera.

- **Step 1**: Install deps and start dev server

```sh
npm i
npm run dev
```

- **Step 2**: Put your iPhone and Mac on the same network
  - Easiest: same Wi‑Fi
  - Also works: plug in iPhone via USB and enable **Personal Hotspot** on iPhone (your Mac will join that network)

- **Step 3**: Find your Mac’s local IP and open the site on iPhone
  - Open in Safari: `https://<your-mac-ip>:8080`
  - If you see a certificate warning, that’s expected for dev. For the most seamless setup, use mkcert (below).

If you prefer to run camera on the desktop, just open the dev URL on your Mac as usual; the camera source is always the camera of the device running the browser.

### Seamless HTTPS (recommended): mkcert

This repo uses `vite-plugin-mkcert` in development. If you install `mkcert` on your Mac, it will generate a locally-trusted HTTPS cert so desktop browsers won’t show warnings.

- Install mkcert (macOS): `brew install mkcert nss`
- Initialize local CA: `mkcert -install`
- Restart `npm run dev`

For iPhone Safari, you can either accept the dev warning (fastest), or fully trust the cert by installing the mkcert root CA on your phone (best UX).

### “No cert prompts” option: run through a tunnel

If you want your phone to open ORBIT with *zero* local certificate work, run a HTTPS tunnel (for example `cloudflared` or `ngrok`) and open the public HTTPS URL on your phone.
