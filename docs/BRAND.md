# Fantasy Sports Bible — the mark

Owner-supplied brand direction (Aug 21) rendered as vector. The identity
is an open book whose pages are a football field, under a gold trophy,
with an **FSB** plaque in the gutter — navy ground, gold rule.

> **Tagline:** DRAFT SMARTER. DOMINATE LONGER.

## The files

All under `frontend/assets/`, served at `/app/assets/…`.

| File | What it is | Used by |
|---|---|---|
| `fsb-logo.svg` | Full lockup — mark, wordmark, tagline | The sign-in page hero |
| `fsb-icon.svg` | Square app icon: mark over **FSB** on its own navy ground | Favicon, `apple-touch-icon`, PWA tile |
| `fsb-mark.svg` | The mark alone, no words | Anywhere the name is already on screen |

`frontend/icons/icon-192.png` and `icon-512.png` are **rendered from
`fsb-icon.svg`** (headless Chromium) for the manifest, which needs raster.
Regenerate them whenever the SVG changes — a home-screen tile that
disagrees with the favicon is the drift this note exists to prevent.

## Why vector, not the supplied PNG

The mark ships as a favicon, a PWA tile and a page hero — 16px to 512px
from one file. A raster mockup cannot do that, and the pasted reference
images never reached the repo as files. The SVG is a few KB, stays crisp
at any size, and can be recoloured by CSS.

**To swap in the exact artwork:** drop the PNG/SVG into
`frontend/assets/`, point `skin.FAVICON` and the login hero at it, and
re-render the two manifest icons. Nothing else references the mark.

## Colours

| Token | Hex | Where |
|---|---|---|
| Navy ground | `#0B1A36` | Page ground behind the mark, icon field, `theme-color` |
| Navy field | `#12244A` | The book's pages |
| Gold | `#E5B32B` | Trophy body, rules, "Sports", the tagline |
| Gold highlight | `#F6D66B` | Top of the trophy gradient |
| Gold shadow | `#B8850F` | Bottom of the trophy gradient |
| Page white | `#F4F6FB` | Yard lines, "Fantasy" and "Bible", FSB |

## Rules of use

- **The mark always sits on navy.** The wordmark is white and gold by
  design; on the light theme's cream ground "Fantasy" and "Bible" vanish
  and the name reads as one gold word. The sign-in hero therefore paints
  its own navy panel in every theme, which is also how the brand is drawn
  everywhere else. Any new placement does the same.
- **The icon carries its own ground.** A favicon cannot borrow the
  page's, so `fsb-icon.svg` paints its own rounded navy tile.
- **Drop the words below ~64px.** `fsb-icon.svg` keeps FSB because it is
  also the home-screen tile; the wordmark lockup is never used small.

## A known trade

The wordmark and tagline are **live SVG text**, not outlines. That keeps
the files tiny and recolourable, at the cost of rendering in whatever
grotesque the device has — so the letterforms are not pixel-identical
across platforms. The tagline pins its own width with `textLength` so the
flanking gold rules land in the right place regardless (without it, a
wider face pushed the words straight through them).

Converting the two text runs to paths would fix the letterforms and cost
a few KB. Worth doing before any printed use; not worth it for a web app.

## Where it appears

Every page this app serves carries `skin.FAVICON` — the app itself, the
sign-in and access pages, league settings, My stuff, the mock draft room,
the draft board, the IDP board and the printable cheat sheet. The
sign-in page is the only surface that shows the full lockup, because it
is the only one that has to introduce the app to someone who has never
seen it.
