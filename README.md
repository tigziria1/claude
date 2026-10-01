# claude
My freelancer website

A one-page website for a freelance digital marketer: SEO, Google Ads, paid social, email and analytics.
Plain HTML, CSS and JavaScript. No build step, no dependencies.

## What's on the page

- **Hero** with headline, call to action and an annotated revenue chart from a client result
- **Services**: SEO, Google Ads, paid social, email, analytics, landing pages
- **Results**: three case studies with before/after numbers
- **Process**: four steps from intro call to monthly reporting
- **Pricing**: audit, monthly retainer and project sprint
- **Testimonials, About, FAQ**
- **Contact form** that opens the visitor's email app, or sends to your inbox through Formspree
- Light and dark mode (follows the visitor's system setting), mobile menu, keyboard accessible

## Files

```
index.html          All page content
css/styles.css      Colors, fonts and layout (colors are variables at the top)
js/main.js          Mobile menu, copy-email button, contact form
assets/favicon.svg  Browser tab icon
```

## Preview it locally

Open `index.html` in a browser, or run a small local server:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Make it yours

Everything you need to change is marked with an `EDIT:` comment in `index.html`.
Search for `EDIT:` and work through the list:

1. **Name.** Replace `Sam Rivera`, `SR` and `Sam` with your own name and initials.
2. **Email.** Replace `hello@example.com` (it appears in the contact section and on the form's `data-email`).
3. **Numbers.** Update the hero stats (years, clients, ad spend) and availability line.
4. **Case studies and chart.** Replace the three results and the hero chart with your own client results.
   Bar widths are set with `style="--w: 42%"`: use `value ÷ largest value on that scale`.
5. **Testimonials.** The quotes are examples. Replace them with real ones from your clients, with their permission.
6. **Prices.** Update the three packages to match what you charge.
7. **About.** Your story, location and certifications. To add a photo, save it as `assets/photo.jpg`
   and follow the comment inside the `.portrait` block.
8. **LinkedIn.** Put your profile URL in the footer link.
9. **Page title and description** in the `<head>`. These are what Google shows in search results.

### Colors and fonts

Colors are defined once at the top of `css/styles.css` (`--accent`, `--mark`, `--ink` and so on), with a
matching set for dark mode right below. Change them there and the whole site follows.

### Receiving form messages

By default the contact form opens the visitor's email app with their message filled in.
To receive messages directly instead:

1. Create a free form at [formspree.io](https://formspree.io).
2. Copy its endpoint, e.g. `https://formspree.io/f/abcdwxyz`.
3. Paste it into `data-endpoint=""` on the `<form id="contact-form">` tag.

## Publish it for free with GitHub Pages

1. Merge this branch into `main`.
2. On GitHub, open **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**, pick `main` and `/ (root)`, then **Save**.
4. After a minute the site is live at `https://<your-username>.github.io/<repo-name>/`.

To use your own domain (for example `yourname.com`), add it under **Custom domain** on the same page.
