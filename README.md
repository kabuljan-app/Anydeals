# Daily Finds: an automatic Amazon affiliate website

Every day, GitHub runs `scripts/fetch_products.py` for free. It pulls products
from the Amazon Creators API with your affiliate tag, refreshes every price,
saves `site/data/products.json`, and republishes the website. You don't need a
server and you don't have to do anything daily.

## One-time setup (about 20 minutes)

### 1. Get Creators API credentials
1. Sign in to Associates Central.
2. Open **Tools > Creators API**, click **Create Application**, then **Create Credential**.
3. Copy the **Credential ID**, **Credential Secret** (shown only once) and **Version** (e.g. `3.1` for the US).
4. Note your **Store ID / tracking tag** (looks like `yourname-20`).

Amazon only grants API access to accounts with recent qualifying sales, and
takes it away if sales stop. If the API refuses your credentials, keep sharing
links normally until you qualify.

### 2. Put the project on GitHub
1. Create a free account at github.com and a new repository (public is needed for free GitHub Pages).
2. Upload all files from this folder, keeping the folders as they are
   (including the hidden `.github/workflows` folder).

### 3. Add your credentials as secrets
Repository **Settings > Secrets and variables > Actions > New repository secret**, add:

| Name | Value |
|---|---|
| `AMAZON_CREDENTIAL_ID` | your Credential ID |
| `AMAZON_CREDENTIAL_SECRET` | your Credential Secret |
| `AMAZON_CREDENTIAL_VERSION` | e.g. `3.1` |
| `AMAZON_PARTNER_TAG` | e.g. `yourname-20` |

Secrets are never visible on the website or in the code.

### 4. Turn on the website
1. **Settings > Pages**, set **Source** to **GitHub Actions**.
2. **Actions** tab, open **Daily product update**, click **Run workflow**.
3. After it finishes (a couple of minutes), your site is live at
   `https://YOUR-USERNAME.github.io/REPO-NAME/`.

From then on it updates itself every day at 11:00 UTC.

## Choosing what shows up

Edit `config.json` on GitHub (click the file, then the pencil icon):

- `categories`: each one becomes a thumbnail tile in the menu.
- `keywords`: searches run daily for that category; new results appear at the top.
- `searchIndex`: Amazon's department name, e.g. `Electronics`, `HomeAndKitchen`,
  `ToysAndGames`, `Beauty`, `SportsAndOutdoors`, `PetSupplies`, `Fashion`, `Books`.
- `asins`: specific products you want listed (the code after `/dp/` in an Amazon link).
- `pagesPerKeyword`: 10 results per page; raise it for more products (more API calls).
- `maxProducts`: the cap on how many products the site keeps.

Saving the file republishes the site; new products arrive on the next daily run.

## How it behaves
- **Newest first:** each product remembers the day it was first found.
  Items from the last 2 days get a "New" label.
- **Deals on top:** products with a live Amazon deal or 10%+ off go in
  "Today's deals", sorted by biggest discount.
- **Quantity:** Amazon doesn't share exact stock counts, so the site shows
  what the API gives: stock status ("In Stock", "Only a few left") and any
  per-order limit.
- **Fresh prices:** every product on the site is re-checked each run. Anything
  out of stock or no longer returned is removed, and the page shows the time
  prices were updated, as Amazon's rules require.
- **Safety net:** if Amazon is down during a run, the old data stays online.

## Changing the look
All styling is at the top of `site/index.html`. Colors are the `--` variables
in the `:root` block; the site name comes from `siteName` in `config.json`.

## Custom domain (optional)
Settings > Pages > Custom domain, then follow GitHub's DNS instructions.
