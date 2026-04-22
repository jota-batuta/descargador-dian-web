# DESIGN.md — DIAN Downloader Web

Identidad visual para `descargasdian.batutaai.com`. Heredada del sistema Batuta AI (origen: [batuta-flow/DESIGN.md](https://github.com/jota-batuta/batuta-flow)). Cualquier cambio a tokens aquí debe alinearse con el sistema padre.

## Origen y versión

- **Sistema padre:** Batuta AI design system (batuta-flow @ `main`, verificado 2026-04-21).
- **Tokens canon:** `batuta-flow/src/index.css` y `batuta-flow/tailwind.config.ts`.
- **Este archivo:** subset aplicado a 3 páginas HTML + 1 correo transaccional. Sin build step: los tokens viven en `frontend/static/brand.css` como CSS custom properties.

## Paleta

Dark-mode first. Proporción aproximada: 60 % nocturno · 30 % bruma · 10 % cobalto.

| Token | HSL | HEX | Uso |
|---|---|---|---|
| `--nocturno` | `hsl(230 36% 9%)` | `#0E1220` | Fondo global |
| `--noche-profunda` | `hsl(227 30% 13%)` | `#161B2E` | Cards, superficies elevadas |
| `--hover-bg` | `hsl(229 36% 16%)` | `#1A1F36` | Hover de filas/items |
| `--bruma-clara` | `hsl(225 36% 95%)` | `#ECEFF6` | Texto primario |
| `--bruma` | `hsl(224 18% 71%)` | `#A8B0C2` | Texto secundario |
| `--bruma-terciaria` | `hsl(226 17% 50%)` | `#6B7593` | Hints, captions, footer |
| `--grafito` | `hsl(228 23% 19%)` | `#262B3D` | Bordes 1px, divisores |
| `--grafito-fuerte` | `hsl(226 21% 29%)` | `#3A4159` | Divisores enfatizados |
| **`--cobalto`** | `hsl(232 100% 65%)` | **`#4D5CFF`** | **Acento primario — batuta. NUNCA recolorear.** |
| `--cobalto-glow` | `hsl(232 100% 70%)` | — | Hover/focus del acento |
| `--cobalto-soft` | `hsl(232 100% 65% / 0.12)` | — | Chips, focus ring, tintes |
| `--esmeralda` | `hsl(158 64% 52%)` | `#34D399` | Éxito (descarga completada) |
| `--amber-warn` | `hsl(43 90% 58%)` | — | Advertencia (limitación DIAN, token expira) |
| `--danger` | `hsl(0 75% 62%)` | — | Error (form inválido, 4xx/5xx) |
| `--terracota` | `hsl(16 56% 59%)` | `#D17A5C` | Editorial (no usado en esta app) |

**Regla dura:** el **baton del logo siempre es cobalto `#4D5CFF`**. No aplicar gradientes sobre la mano del origami. El cobalto nunca se usa como fondo ancho: sólo en botones primarios, focus rings, chips y el acento tipográfico de "AI".

## Tipografía

| Familia | Pesos | Uso |
|---|---|---|
| **Inter** | 400, 500, 600, 700 | Toda la UI y correo (body + display) |
| **JetBrains Mono** | 400, 500 | Contadores de progreso, eyebrows, labels técnicos |
| **Playfair Display** italic | — | Editorial. No usada en esta app (reservado). |

Carga vía Google Fonts en cada HTML:

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

Eyebrows: mono 11-12 px, UPPERCASE, tracking `0.08em`, color `var(--cobalto)`.

## Logo

- **Símbolo SVG:** `/static/logo.svg` — rectángulo redondeado cobalto con trazo bruma-clara representando la batuta.
- **Wordmark:** HTML + CSS. "Batuta" en `var(--bruma-clara)` + "AI" en `var(--cobalto)`, peso 700.
- **Favicon:** `/static/favicon.svg` (mismo archivo que el símbolo).
- **Logo para correo:** `/static/logo.png` (raster, 32×32 @2x). Gmail strips inline SVG.

Markup estándar para todos los headers:

```html
<a href="https://www.batutaai.com" target="_blank" rel="noopener"
   class="bt-brand" aria-label="Batuta AI — sitio principal">
  <img src="/static/logo.svg" alt="" width="32" height="32">
  <span>Batuta <span class="bt-brand-accent">AI</span></span>
</a>
```

El logo **siempre** enlaza a `https://www.batutaai.com` en nueva pestaña. El alt del `<img>` es vacío porque el texto adyacente ya comunica la marca (evita lectura duplicada por screen readers).

## Primitives (clases en `brand.css`)

- `.bt-card` — superficie elevada (fondo `--noche-profunda`, borde `--grafito`, radius 12 px, shadow sutil).
- `.bt-header` — sticky top bar (h 64 px, blur-backdrop, borde inferior).
- `.bt-input` / `.bt-textarea` — inputs dark (fondo nocturno, borde grafito, focus cobalto con ring 3 px).
- `.bt-label` — label sans 13 px, bruma, tracking ligero.
- `.bt-hint` — hint 12 px, bruma-terciaria.
- `.bt-btn` — base de botón (flex center, radius 8 px, transición color + transform).
- `.bt-btn-primary` — CTA principal, fondo cobalto, width 100 %.
- `.bt-btn-success` — botón de descarga, fondo esmeralda, texto nocturno.
- `.bt-btn-ghost` — secundario, transparente con borde grafito.
- `.bt-chip` — badge pequeño cobalto sobre cobalto-soft, radius pill.
- `.bt-alert-error` — banda danger-soft con borde danger.
- `.bt-alert-warning` — banda amber-warn-soft con borde amber.
- `.bt-progress-wrap` / `.bt-progress-fill` — barra de progreso con gradiente cobalto.
- `.bt-hero-glow` + `.bt-above-glow` — fondo radial sutil (solo auth cards).
- `.bt-footer-link` — links secundarios debajo de forms.

## Correo transaccional

- **Subject:** `Bienvenido a Batuta AI — DIAN Downloader`
- **From:** `Batuta AI <jota@batutaai.com>` (según `.env`: `SMTP_USER=jota@batutaai.com`)
- **Layout:** tabla, inline styles. Nada de `<style>` global (Gmail lo strippa). Sin CSS vars.
- **Logo:** `<img src="https://descargasdian.batutaai.com/static/logo.png">` — URL absoluta, PNG para compatibilidad con Outlook.
- **CTA:** botón `#4D5CFF`, texto blanco, padding 13×34 px, radius 8 px.
- **Footer:** "Batuta AI SAS · www.batutaai.com" + disclaimer.

## Accesibilidad

- Texto bruma-clara (`#ECEFF6`) sobre nocturno (`#0E1220`) → ratio ≈ 17:1 (AAA).
- Texto bruma (`#A8B0C2`) sobre nocturno → ratio ≈ 9:1 (AAA).
- Texto bruma-terciaria (`#6B7593`) sobre nocturno → ratio ≈ 5:1 (AA). No usar para texto principal.
- Cobalto sobre fondo oscuro → ratio ≈ 5.3:1 (AA). Válido para botones/acentos; no para bodies.
- Focus states visibles: `box-shadow: 0 0 0 3px var(--cobalto-soft)` sobre inputs.
- Cada botón tiene estado `:disabled` con opacidad 0.5 y `cursor: not-allowed`.
- Links con `aria-label` cuando el texto visible no comunica destino (logo → sitio principal).

## Qué NO hacer

- ❌ Recolorear el baton del logo (siempre cobalto).
- ❌ Aplicar gradientes al cobalto sólido del logo.
- ❌ Usar light-mode como tema por defecto.
- ❌ Introducir nuevas familias tipográficas sin actualizar este doc.
- ❌ Hardcodear hex en HTML — siempre `var(--*)` desde `brand.css`.
- ❌ Cambiar el texto del acento en el wordmark ("AI" es siempre cobalto, el resto bruma-clara).

## Referencias

- Repo padre: https://github.com/jota-batuta/batuta-flow (`src/index.css`, `tailwind.config.ts`, `src/components/Logo.tsx`, `DESIGN.md`).
- Sitio principal: https://www.batutaai.com
- Este servicio: https://descargasdian.batutaai.com
